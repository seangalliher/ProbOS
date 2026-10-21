# BF-911: agents cannot rewrite the running vessel's config files (#1613)

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-21
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-21: Amendment A1 (end of this file), re-anchored on `d2447e09`, the final AD-1344 S1 commit
**Status:** build-ready contract. **Tier: HIGH** (a Captain-only credential and the vessel's governance settings).
**Number:** BF-911 is allocated (#1613). Ceilings run 2026-10-21: `scripts/ad_ceiling.py` CEILING AD-1346, NEXT AD-1347 (git subjects, 1,452 issue titles, prompt filenames); BF: `git log --all` subjects top out at BF-910 and `prompts/bf-91*.md` holds only `bf-910-…`. Nothing allocated here.
**Base:** `d2447e09`, the final AD-1344 S1 commit on `origin/main` `7171aded` (tree `5e72cb12c1451e723e1a1822f2f73b6bf92bcb36`; it merges as "Part of #1596"; contract `prompts/ad-1344-s1-constitution-write-refusal.md` with its Amendment A1). Drafted on S1's round-1 candidate `f3747799`; Amendment A1 (end of this file) re-anchors on `d2447e09`. **Build only after S1 merges**; the orchestrator re-runs every SEARCH on the merged main and amends through the Architect if S1 moved. The S1 lines each anchor depends on are listed under "Dependence on AD-1344 S1".
**Ruling:** option A of the Architect's 10:36Z ruling on #1613. What changed since the ruling is listed under "Changes since the ruling".
**Estimated tests:** 40 test functions (about 114 collected items) in one new file; T36–T40 added by Amendment A1. No existing test file changes.

---

## Problem

- BF-908 (#1605) put the config files that can hold `auth.crew_scope_token` on the read floor: `protected_config_files(runtime)` (`security/file_access.py:202-228`) names `runtime.config_path`, the checkout's `config/system.yaml` (`_REPO_DEFAULT_CONFIG`, `:59`) and `~/.probos/config.yaml`. Its callers are all reads (Absence Verified, row 1).
- SWE-harness `write_file` (`cognitive/swe_harness/tools.py:970`) and `edit_file` (`:1054`) join a relative path to `_PROJECT_ROOT` (`:76`, `parents[3]` = `<checkout>/src`) or take an absolute path as given (`_resolve_path`, `:242-245`). After AD-1344 S1 they refuse only the constitution (`:1014`, `:1103`), judging `path_text`, their one conversion of the caller's path (`:1013`, `:1102`). The orchestrator's probe (`probe-r6-output.txt`, on S1's round-1 candidate) rewrote `<layout>/config/system.yaml` through `write_file` by `../config/system.yaml` and by its absolute path.
- `FileWriterAgent` (`agents/file_writer.py:111`, `:145`), reached after consensus (`runtime.py:4782`) and directly by the bundled agents (`organizer_agents.py:65`, `productivity_agents.py:125`), and the office writers (`skill_framework.py:209`, `:261`, `:408`, `:533`) refuse only the constitution too.
- The bundled notes agent joins a model-chosen filename to `~/.probos/notes` (`organizer_agents.py:187-191`), so `../config.yaml` names `~/.probos/config.yaml`. When that file does not exist, writing it creates the file `_resolve_config_path` selects when no `--config` is given (`__main__.py:492-503`).
- A config file can carry the token: `credential_store.crew_scope_token` (`credential_store.py:428`) falls back to `configured_crew_scope_token` (`security/crew_scope.py:99-107`).

## Solution

`security/file_access.py` gains `protected_write_refusal(path, *, root=None, runtime=None) -> str | None`, the write side of BF-908's floor. It returns a one-line reason naming BF-911 for:

1. a value that is not an exact `str` (nothing of it is read or formatted);
2. a path whose resolved form names a file in `protected_config_files(runtime)`, whether or not that file exists, compared component by component in BF-894's canonical form (separators, `..`, case, trailing dots and spaces, HFS+-ignorable code points, NTFS stream suffixes, `\\?\`, `\\.\` and `\\?\UNC\` prefixes; an 8.3 short form with the same first two characters matches);
3. a path whose resolved last component is a credential vault file name (`PROTECTED_LEAF_NAMES`, `:66-69`), in the same canonical form;
4. an existing file with the `os.stat` identity of an existing protected config file (a hard link);
5. an `os.stat` that raises `OSError` or `ValueError` other than not-found, or a resolution that raises `OSError`, `RuntimeError` or `ValueError`.

Any other exception propagates to the writer. A copy in another tree (a worktree's `config/system.yaml`) has another path and another identity, so it is not refused. The eight agent-facing write functions that call AD-1344's rule call this one right after it, each passing the runtime it holds; `FileWriterAgent.commit_write` gains a keyword-only `runtime` that the consensus commit and the bundled agents' direct write pass. The builder boundary, the visiting session's handler, hooks, CI, `config/` and the Captain's channels are untouched.

---

## Re-verification of the ruling on this tree

| Claim in the ruling | On this tree | Evidence |
|---|---|---|
| `operator_checkout_refusal` (`builder_paths.py:312`) refuses a build in the running checkout | **True, moved** to `:447-484` (S1 added lines above it) | `work_dir` is refused when its nearest `.git` entry is `operator_root`'s (`:470-477`); a linked worktree has its own entry and passes (`:457-458`) |
| Called at `builder.py:3161` and `routers/build.py:118` | **True** | `builder.py:3161` `operator_checkout_refusal(work_dir, _PROJECT_ROOT)` with `_PROJECT_ROOT` = `parents[4]` of `builder.py` = the checkout (`:48`); `routers/build.py:118` with `_REPO_ROOT` = `parents[3]` = the checkout (`:29`) |
| So a build's legitimate `config/system.yaml` edit lands in another tree | **True**, pinned by T31 | `execute_approved_build` runs the check before any git command or write (`builder.py:3158-3164`); BF-894 `_LEGIT` keeps `config/system.yaml` (`test_bf894…:31`), `test_builder_guardrails.py:36` |
| The SWE tools resolve against the running checkout (`tools.py:75`, `:241`) | **True, moved** to `:76`, `:242-245` | `_PROJECT_ROOT` = `<checkout>/src`; the live file is `../config/system.yaml` from there |
| `effect_broker_enabled` defaults to `False` (`config.py:3819`) | **True** | `config.py:3819` |
| Option A's caller list: `write_file`, `edit_file`, `FileWriterAgent` (proposal and `commit_write`), the four office writers | **True**; the runtime question is resolved in D4 | the same eight functions as S1's `_EXPECTED_CALLERS` minus `builder_write_refusal` |

**Which file is "the live config", per writer.** `protected_config_files(runtime)` is the definition, read at call time:

| Writer | How it names a file | What a relative `config/system.yaml` means there | The live files it can reach |
|---|---|---|---|
| `write_file`, `edit_file` | relative to `_PROJECT_ROOT` (`<checkout>/src`), or absolute | `<checkout>/src/config/system.yaml`: not a protected file, stays writable (T3, T21) | `../config/system.yaml` (the checkout default), and any protected file by absolute path or link |
| `FileWriterAgent` (proposal, write) | `Path(path)`: relative to the working directory, or absolute | `<cwd>/config/system.yaml`: protected only when the working directory is the checkout | every protected file |
| office writers | `Path(os.path.expanduser(...))`: relative to the working directory, `~` expanded, or absolute | as above | every protected file, `~/.probos/config.yaml` by `~` |
| bundled agents (`_mesh_write_file`) | an absolute path under `~/.probos/` built from the model's filename | — | `~/.probos/config.yaml` by `notes/../config.yaml` |

**When the writer's checkout is not the runtime's.** `_REPO_DEFAULT_CONFIG` is the checkout that holds the running code (`file_access.py:59`, equal to `__main__._repo_default_config_path()`, pinned by `test_bf908_floor_and_children.py:299`), and `runtime.config_path` is the file the vessel loaded (`__main__.py:639`). A file in another checkout or worktree has a different resolved path and a different `os.stat` identity, so it stays writable (T6, T21, T25, T31). A hard link to a protected file, or a path through a junction or symlink that resolves to one, is refused (T10, T11, T13, T22, T25, T30).

---

## Changes since the ruling

| D | Change | Why |
|---|---|---|
| D2 | Absent protected files are refused by name. | `~/.probos/config.yaml` need not exist; creating it changes which file the next start loads without `--config` (`__main__.py:492-503`). The bundled notes agent reaches it (`organizer_agents.py:187-191`). The ruling named only "by resolved path and identity". |
| D4 | The runtime is passed by instance; `FileWriterAgent.commit_write` gains `*, runtime: Any = None`, passed by `runtime.py:4782` and both `_mesh_write_file`. | The ruling left the static `commit_write` open. **Shared contract:** a public signature change, backward compatible. |
| D9 | A sibling census in the new file pairs the two rules' callers; S1's test file is not edited. | Keeps S1's tables truthful and its test file's hash unchanged. |
| D10 | The canonical-form helpers are mirrored in `security`, with a parity test, instead of imported from `cognitive`. | `execution/workspace.py:53` imports `file_access` at module scope; importing `cognitive` from `security` reverses the dependency and risks a cycle. |
| D11, D12 | The vault is refused by name only; the data directory is not on the write floor. | Out of #1613's scope; residuals R4. |

---

## Decisions

| # | Decision | Rejected alternatives |
|---|---|---|
| D1 | The rule is `security.file_access.protected_write_refusal(path, *, root=None, runtime=None) -> str \| None`, beside `protected_config_files`, so the read and write sides read one list. | **B** (generalise `builder_paths.constitution_write_refusal`): mixes a Captain-document rule with a credential rule, has no runtime for `--config`, and changes S1's shared contract. A new `security/` module: a second home for the floor's lists. |
| D2 | The protected set is `protected_config_files(runtime)` (exists or not) plus `PROTECTED_LEAF_NAMES` by last component. | S1's tail match (`…/config/system.yaml` in any tree): refuses every worktree's copy, which builds and SWE work in worktrees need. |
| D3 | Matching: the resolved path's key (D10's canonical form, 8.3 accepted per component) against each protected file's key; then `os.stat` identity with each existing protected file; vault names on the resolved last component. A target that is not on disk ends the identity loop (it is no second name of an existing file). | Lexical only: misses hard links (CVE-2025-59829 class). A lock or mode change on the file: friction for the Captain's editor and the HXI settings route. **C** (refuse only edits that change `auth.crew_scope_token`): fragile with partial edits and leaves every other setting and the operator's local edits open. **D** (keyring only, no token from any agent-writable file): changes the credential model; deferred. |
| D4 | **The runtime problem.** Each writer passes the runtime it holds: the SWE tools `self._runtime`; `FileWriterAgent.act` and the office writers `self._runtime` (`BaseAgent`, `substrate/agent.py:55`); `commit_write` takes `*, runtime: Any = None`; `submit_write_with_consensus` passes `runtime=self`; both `_mesh_write_file` pass their `runtime` argument. With no runtime, `protected_config_files(None)` still names the checkout default and `~/.probos/config.yaml`. | **Boot-time registration** (a module-level "loaded config" the rule reads): mutable module state, two runtimes in one test process see each other's file, and a global lookup where constructor injection exists. **Pure function of the config path** (defaults only): never sees a `--config` file outside the checkout and home. **Changing `commit_write` to an instance method**: every caller and the consensus table change. |
| D5 | Each call sits right after AD-1344's call, inside the same `try` where the writer has one (SWE tools, `FileWriterAgent`); the office writers have none, as on the base. | Before AD-1344's call: S1's reasons and mutation rows would change. |
| D6 | No change to the builder boundary (`builder_paths.py`) or `builder.py`. T31 pins that a build still edits a worktree's `config/system.yaml` while the live file is protected. | Calling the rule from `builder_write_refusal`: changes S1's shared contract for a case BF-897 already covers (residual R7 states the link case). |
| D7 | No change to the Copilot adapter. `_session_relative` admits only paths strictly inside the session directory after `realpath` (`copilot_adapter.py:269-293`). | — |
| D8 | Error shapes as AD-1344's D9: `ToolResult(error=...)`, `{"success": False, "error": ...}`, `PermissionError`. | — |
| D9 | Census in the new file: the callers (T32), the pairing with AD-1344's callers minus `builder_write_refusal` (T33), every `commit_write` call passes `runtime=` (T34), the Captain's channels (T35). S1's test file is unchanged; the new file imports S1's AST and fixture helpers. | Editing S1's `_WRITE_SITES`/`_EXPECTED_CALLERS`: makes S1's campaign of record stale for that file. |
| D10 | `_canonical_name`, `_SHORT_NAME`, `_HFS_IGNORABLE` and `_exception_class_name` mirror BF-894/AD-1344's helpers in `file_access.py` (`_exception_class_name` is the body of S1's `_exception_name` after its A1 D22, `builder_paths.py:87-96`); T19 pins the canonical form's parity, T36 the class name's. | Importing `builder_paths` into `security`: a `cognitive` dependency in the floor that `execution/workspace.py` imports at module scope. |
| D11 | Vault files are refused by name, not identity. | Identity needs the vault's configured location, which the rule has no config for. |
| D12 | The data directory (governance databases) is not on the write floor. | Out of #1613's scope; the workspace lives under it (`file_access.py:26-28`). |
| D13 | No config field; `config/system.yaml` untouched; zero-config boot unchanged. No roadmap row (the Bug Tracker table stops at BF-683; `BF-9[01]x` has 0 rows). | — |
| D14 | No seam registration: no new place where agent work starts (AD-1343 registry unaffected). | — |
| D15 | (A1; S1 D21) In the SWE tools the call judges `path_text`, S1's one conversion of the caller's path (`tools.py:1013`, `:1102`). It sits between S1's refusal block and `target = _resolve_path(path_text)`, so the text both rules judge is the text the tool resolves, writes and returns. The order of D5 is kept: AD-1344's call, then BF-911's. (T38; S1's T38 counts the conversions too.) | `str(path)`, as drafted: a second call of the caller's `__str__` (S1 round-1 F2), and S1's T38 (`test_ad1344…:632`, `:639`) asserts one. BF-911's call first: S1's reasons and campaign rows would change (D5). |
| D16 | (A1; S1 D20) Each of BF-911's eight log lines is a constant, `BF-911 <Writer> refused operation=<op> reason_code=protected_write_refused`, with `<op>` one of `write_file`, `edit_file`, `propose_write`, `commit_write`, `docx_create`, `docx_revise`, `pptx_create`, `xlsx_update`. It formats nothing, so it is the same with and without the strict effect context. The returned or raised refusal still names the path. An exception from a logging filter (outside `Handler.handleError`), like one the rule raises, enters the handlers of the `try` that holds the call, in their order: `write_file` `except Exception` (`tools.py:1041`); `edit_file` `except FileNotFoundError` (`:1161`), then `except Exception` (`:1169`); `FileWriterAgent` `except Exception` (`file_writer.py:131`, `:156`); the office writers have no `try`, so it reaches `handle_intent`'s caller. (T37, T39, T40) | Logging the reason, as drafted: it holds `repr(path)`, so the caller's path reaches a shared log, under the strict context too (S1 round-1 F1). One code per refusal kind: the returned reason already names the kind. Changing S1's adjacent lines in `file_writer.py` and `skill_framework.py`: S1's contract (R10). |
| D17 | (A1; S1 D22) `_exception_class_name` returns the class name read through `type`'s descriptor when the metaclass is exactly `type` and the name is an exact-`str` identifier, else `Exception`. (T16, T36) | Importing S1's helper: D10. |

---

## Dependence on AD-1344 S1 (anchors on this tree)

| Section | S1 lines the SEARCH contains |
|---|---|
| 2b, 2c (A1-1, A1-2) | `tools.py:1016-1018`, `:1105-1107` (S1's constant `logger.warning("AD-1344 … reason_code=constitution_refused")`, `return ToolResult(error=refused)` and `target = _resolve_path(path_text)`); `path_text` from `:1013`, `:1102` |
| 3a, 3b, 3c | `file_writer.py:9` (S1's import), `:113-114`, `:145-148` |
| 6b–6e | `skill_framework.py:211-212`, `:263-264`, `:410-411`, `:535-536` |
| Section 8 | `DECISIONS.md:455` (S1's entry, with its Amendment A1 bullet `:463` and campaign bullet `:466`, precedes the anchor at `:469`); `PROGRESS.md:3` (S1's entry follows the anchor) |
| Section 7 (imports) | `tests/test_ad1344_constitution_write_refusal.py`: `_dir_link` `:111`, `_build` `:456`, `_ShiftingPath` `:614`, `_CHANNEL_SUFFIXES` `:788`, `_tracked` `:791`, `_calls` `:800`, `_callee` `:820`, `_source` `:852`; T33 reads S1's caller set from the code |

---

## Implementation

### Section 0: Event types

None.

### Section 1: `src/probos/security/file_access.py`

**1a** (imports)

SEARCH:
```python
import logging
import ntpath
import os
import stat
```
REPLACE:
```python
import logging
import ntpath
import os
import posixpath
import re
import stat
```

**1b** (module docstring)

SEARCH:
```python
absolute path" -- and raising that is Tier 2 (AD-995). This module closes the
ungoverned, unaudited, one-tag route, which is the part that was wrong.
"""
```
REPLACE:
```python
absolute path" -- and raising that is Tier 2 (AD-995). This module closes the
ungoverned, unaudited, one-tag route, which is the part that was wrong.

BF-911 (#1613): the write side. ``protected_write_refusal`` refuses an agent-reachable
write to a file in :func:`protected_config_files` or to a credential vault file name
(``PROTECTED_LEAF_NAMES``), by resolved path and by ``os.stat`` identity. Its callers are
listed in ``tests/test_bf911_protected_config_write_refusal.py`` (``_EXPECTED_CALLERS``).
"""
```

**1c** (the rule, after `protected_config_files`)

SEARCH:
```python
        if resolved not in files:  # BF-908 A3: the loaded file is often a default; list each file once
            files.append(resolved)
    return files
```
REPLACE:
```python
        if resolved not in files:  # BF-908 A3: the loaded file is often a default; list each file once
            files.append(resolved)
    return files


# BF-911 (#1613): the write side of the floor. Components are compared in BF-894's canonical
# form (``builder_paths._canonical``: HFS+ ignorable code points dropped, trailing dots and
# spaces trimmed, upper-cased) with its 8.3 short-name pattern. Mirrored here so this module
# imports nothing from ``cognitive``; tests/test_bf911_protected_config_write_refusal.py T19
# pins the parity.
_HFS_IGNORABLE = re.compile("[\u200c-\u200f\u202a-\u202e\u206a-\u206f\ufeff]")
_SHORT_NAME = re.compile(r"~[0-9]")
# The Win32 file and device namespace prefixes, with separators already ``/``.
_DEVICE_PREFIXES = ("//?/", "//./")
_CONFIG_FILE = "a protected config file (the loaded --config, the checkout's config/system.yaml or ~/.probos/config.yaml)"
_VAULT_FILE = "a credential vault file"
_NOT_A_STR = "Protected write refused (BF-911): the path is not an exact str, so it is not checked"


def _canonical_name(part: str) -> str:
    """One component in the form a case-insensitive filesystem compares it (BF-894's form)."""
    return _HFS_IGNORABLE.sub("", part).rstrip(" .").upper()


_PROTECTED_LEAF_KEYS = frozenset(_canonical_name(name) for name in PROTECTED_LEAF_NAMES)


def _write_key(path_text: str) -> tuple[str, ...]:
    """BF-911: the components of *path_text* in the form the write floor compares them.

    Separators become ``/``; a ``//?/`` or ``//./`` prefix is dropped and ``//?/UNC/``
    becomes ``//``; the drive (``C:`` or ``//server/share``), upper-cased, is the first
    component; ``..`` is collapsed; each other component loses any ``:`` suffix (an NTFS
    stream) and is put in canonical form, and components then empty are dropped.
    """
    unified = path_text.replace("\\", "/")
    if unified[:4] in _DEVICE_PREFIXES:
        unified = unified[4:]
        if unified[:4].upper() == "UNC/":
            unified = "//" + unified[4:]
    drive, rest = ntpath.splitdrive(unified)
    names = [_canonical_name(part.split(":", 1)[0]) for part in posixpath.normpath(rest or "/").split("/")]
    return (drive.upper(), *(name for name in names if name))


def _same_key(candidate: tuple[str, ...], protected: tuple[str, ...]) -> bool:
    """Whether *candidate* names *protected*: each component equal, or an 8.3 short form with its first two characters."""
    return len(candidate) == len(protected) and all(
        name == expected or (_SHORT_NAME.search(name) is not None and name[:2] == expected[:2])
        for name, expected in zip(candidate, protected)
    )


def _exception_class_name(exc: BaseException) -> str:
    """The class name of *exc*, read through ``type``'s own descriptor, if it is an exact-``str`` identifier.

    ``Exception`` under another metaclass (nothing of the class is read) or for any other name.
    The body of AD-1344's ``builder_paths._exception_name``; T36 compares the two.
    """
    cls = type(exc)
    if type(cls) is not type:
        return "Exception"
    name = cls.__name__
    return name if type(name) is str and name.isidentifier() else "Exception"


def _protected_refusal(path_text: str, what: str) -> str:
    return f"Protected write refused (BF-911): {path_text!r} is {what}, which an agent does not write"


def _protected_unverifiable(path_text: str, stage: str, exc: BaseException) -> str:
    return (
        f"Protected write refused (BF-911): cannot verify that {path_text!r} is not a protected "
        f"config or credential file ({stage}: {_exception_class_name(exc)})"
    )


def protected_write_refusal(
    path: str, *, root: str | os.PathLike[str] | None = None, runtime: Any = None,
) -> str | None:
    """BF-911 (#1613): why an agent-reachable writer must not write *path*, or None if it may.

    *path* is the path as the writer received it: relative to *root*, or to the working
    directory when *root* is None, or absolute. *runtime* supplies ``config_path``; see
    :func:`protected_config_files` for the files named with and without it. Refused, with a
    one-line reason naming BF-911: a value that is not an exact ``str`` (nothing of it is
    read); a path whose resolved form names one of those files, whether or not it exists,
    or whose resolved last component is in ``PROTECTED_LEAF_NAMES`` (compared by
    :func:`_write_key`, an 8.3 short form accepted for a config file's components); an
    existing file with the ``os.stat`` identity of an existing protected config file; an
    ``os.stat`` that raises ``OSError`` or ``ValueError`` other than ``FileNotFoundError`` or
    ``NotADirectoryError``; and a resolution that raises ``OSError``, ``RuntimeError`` or
    ``ValueError``. Any other exception propagates. A file at another path with another
    identity, such as a worktree's ``config/system.yaml``, is not refused.
    """
    if type(path) is not str:
        return _NOT_A_STR
    target = Path(path)
    if root is not None and not target.is_absolute():
        target = Path(root) / target
    try:
        resolved = target.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        return _protected_unverifiable(path, "resolved", exc)
    key = _write_key(str(resolved))
    if key[-1] in _PROTECTED_LEAF_KEYS:
        return _protected_refusal(path, _VAULT_FILE)
    configs = protected_config_files(runtime)
    if any(_same_key(key, _write_key(str(config))) for config in configs):
        return _protected_refusal(path, _CONFIG_FILE)
    for config in configs:
        try:
            config_stat = os.stat(config)
        except (FileNotFoundError, NotADirectoryError):
            continue  # not on disk: the name comparison above is the whole check
        except (OSError, ValueError) as exc:
            return _protected_unverifiable(path, "config", exc)
        try:
            current = os.stat(target)
        except (FileNotFoundError, NotADirectoryError):
            return None  # not on disk, so not a second name of an existing config file
        except (OSError, ValueError) as exc:
            return _protected_unverifiable(path, "target", exc)
        if os.path.samestat(current, config_stat):
            return _protected_refusal(path, _CONFIG_FILE)
    return None
```

### Section 2: `src/probos/cognitive/swe_harness/tools.py`

**2a**

SEARCH:
```python
    permitted_read_roots,
    protected_read_roots,
    read_verified_file,
```
REPLACE:
```python
    permitted_read_roots,
    protected_read_roots,
    protected_write_refusal,
    read_verified_file,
```

**2b** (`WriteFileTool.invoke`, after AD-1344's check, inside the existing `try`) - replaced by Amendment A1 (A1-1), re-anchored on `d2447e09`

SEARCH:
```python
                logger.warning("AD-1344 WriteFileTool refused operation=write_file reason_code=constitution_refused")
                return ToolResult(error=refused)
            target = _resolve_path(path_text)  # AD-1344: write_file, the text the rule judged
```
REPLACE:
```python
                logger.warning("AD-1344 WriteFileTool refused operation=write_file reason_code=constitution_refused")
                return ToolResult(error=refused)
            refused = protected_write_refusal(path_text, root=_PROJECT_ROOT, runtime=self._runtime)  # BF-911: write_file
            if refused is not None:
                logger.warning("BF-911 WriteFileTool refused operation=write_file reason_code=protected_write_refused")
                return ToolResult(error=refused)
            target = _resolve_path(path_text)  # AD-1344: write_file, the text the rule judged
```

**2c** (`EditFileTool.invoke`, the same place) - replaced by Amendment A1 (A1-2), re-anchored on `d2447e09`

SEARCH:
```python
                logger.warning("AD-1344 EditFileTool refused operation=edit_file reason_code=constitution_refused")
                return ToolResult(error=refused)
            target = _resolve_path(path_text)  # AD-1344: edit_file, the text the rule judged
```
REPLACE:
```python
                logger.warning("AD-1344 EditFileTool refused operation=edit_file reason_code=constitution_refused")
                return ToolResult(error=refused)
            refused = protected_write_refusal(path_text, root=_PROJECT_ROOT, runtime=self._runtime)  # BF-911: edit_file
            if refused is not None:
                logger.warning("BF-911 EditFileTool refused operation=edit_file reason_code=protected_write_refused")
                return ToolResult(error=refused)
            target = _resolve_path(path_text)  # AD-1344: edit_file, the text the rule judged
```

### Section 3: `src/probos/agents/file_writer.py`

**3a**

SEARCH:
```python
from probos.cognitive.builder_paths import constitution_write_refusal
from probos.substrate.agent import BaseAgent
```
REPLACE:
```python
from probos.cognitive.builder_paths import constitution_write_refusal
from probos.security.file_access import protected_write_refusal
from probos.substrate.agent import BaseAgent
```

**3b** (`act`, the proposal) - replaced by Amendment A1 (A1-3), re-anchored on `d2447e09`

SEARCH:
```python
                    logger.warning("AD-1344 FileWriterAgent proposal refused: %s", refused)
                    return {"success": False, "error": refused}
                parent = p.parent
```
REPLACE:
```python
                    logger.warning("AD-1344 FileWriterAgent proposal refused: %s", refused)
                    return {"success": False, "error": refused}
                refused = protected_write_refusal(str(p), runtime=self._runtime)  # BF-911: the proposal
                if refused is not None:
                    logger.warning("BF-911 FileWriterAgent refused operation=propose_write reason_code=protected_write_refused")
                    return {"success": False, "error": refused}
                parent = p.parent
```

**3c** (`commit_write`: keyword-only `runtime`, and the check) - replaced by Amendment A1 (A1-4), re-anchored on `d2447e09`

SEARCH:
```python
    @staticmethod
    async def commit_write(path: str, content: str) -> dict[str, Any]:
        """Actually write the file. Called by the runtime after consensus approval."""
        try:
            p = Path(path)
            refused = constitution_write_refusal(str(p), Path.cwd())  # AD-1344: the write
            if refused is not None:
                logger.warning("AD-1344 FileWriterAgent write refused: %s", refused)
                return {"success": False, "error": refused}
            p.parent.mkdir(parents=True, exist_ok=True)
```
REPLACE:
```python
    @staticmethod
    async def commit_write(path: str, content: str, *, runtime: Any = None) -> dict[str, Any]:
        """Actually write the file. Called by the runtime after consensus approval.

        BF-911: *runtime* supplies the vessel's loaded config file to
        ``file_access.protected_write_refusal``; without it the checkout's
        ``config/system.yaml`` and ``~/.probos/config.yaml`` are still refused.
        """
        try:
            p = Path(path)
            refused = constitution_write_refusal(str(p), Path.cwd())  # AD-1344: the write
            if refused is not None:
                logger.warning("AD-1344 FileWriterAgent write refused: %s", refused)
                return {"success": False, "error": refused}
            refused = protected_write_refusal(str(p), runtime=runtime)  # BF-911: the write
            if refused is not None:
                logger.warning("BF-911 FileWriterAgent refused operation=commit_write reason_code=protected_write_refused")
                return {"success": False, "error": refused}
            p.parent.mkdir(parents=True, exist_ok=True)
```

### Section 4: `src/probos/runtime.py` (`submit_write_with_consensus`)

SEARCH:
```python
                # Commit the write
                commit_result = await FileWriterAgent.commit_write(path, content)
                committed = commit_result.get("success", False)
```
REPLACE:
```python
                # Commit the write
                commit_result = await FileWriterAgent.commit_write(path, content, runtime=self)  # BF-911: the loaded config file too
                committed = commit_result.get("success", False)
```

### Section 5: the bundled agents' direct write

**5a** `src/probos/agents/utility/organizer_agents.py`

SEARCH:
```python
    from probos.agents.file_writer import FileWriterAgent

    result = await FileWriterAgent.commit_write(path, content)
    return result.get("success", False)
```
REPLACE:
```python
    from probos.agents.file_writer import FileWriterAgent

    result = await FileWriterAgent.commit_write(path, content, runtime=runtime)  # BF-911: the loaded config file too
    return result.get("success", False)
```

**5b** `src/probos/agents/utility/productivity_agents.py`

SEARCH:
```python
    from probos.agents.file_writer import FileWriterAgent

    result = await FileWriterAgent.commit_write(path, content)
    return result.get("success", False)
```
REPLACE:
```python
    from probos.agents.file_writer import FileWriterAgent

    result = await FileWriterAgent.commit_write(path, content, runtime=runtime)  # BF-911: the loaded config file too
    return result.get("success", False)
```

### Section 6: `src/probos/skill_framework.py`

**6a**

SEARCH:
```python
from probos.protocols import ConnectionFactory, DatabaseConnection
from probos.substrate.skill_agent import SkillBasedAgent
```
REPLACE:
```python
from probos.protocols import ConnectionFactory, DatabaseConnection
from probos.security.file_access import protected_write_refusal
from probos.substrate.skill_agent import SkillBasedAgent
```

**6b** (`create_docx`) - replaced by Amendment A1 (A1-5), re-anchored on `d2447e09`

SEARCH:
```python
                logger.warning("AD-1344 DocxAgent refused: %s", refused)
                raise PermissionError(refused)
            target.parent.mkdir(parents=True, exist_ok=True)
            doc.save(str(target))
```
REPLACE:
```python
                logger.warning("AD-1344 DocxAgent refused: %s", refused)
                raise PermissionError(refused)
            refused = protected_write_refusal(str(target), runtime=self._runtime)  # BF-911: docx_create
            if refused is not None:
                logger.warning("BF-911 DocxAgent refused operation=docx_create reason_code=protected_write_refused")
                raise PermissionError(refused)
            target.parent.mkdir(parents=True, exist_ok=True)
            doc.save(str(target))
```

**6c** (`revise_docx`) - replaced by Amendment A1 (A1-6), re-anchored on `d2447e09`

SEARCH:
```python
            logger.warning("AD-1344 DocxAgent refused: %s", refused)
            raise PermissionError(refused)

        doc = Document(str(source))
```
REPLACE:
```python
            logger.warning("AD-1344 DocxAgent refused: %s", refused)
            raise PermissionError(refused)
        refused = protected_write_refusal(str(source), runtime=self._runtime)  # BF-911: docx_revise
        if refused is not None:
            logger.warning("BF-911 DocxAgent refused operation=docx_revise reason_code=protected_write_refused")
            raise PermissionError(refused)

        doc = Document(str(source))
```

**6d** (`create_pptx`) - replaced by Amendment A1 (A1-7), re-anchored on `d2447e09`

SEARCH:
```python
                logger.warning("AD-1344 PptxAgent refused: %s", refused)
                raise PermissionError(refused)
            target.parent.mkdir(parents=True, exist_ok=True)
```
REPLACE:
```python
                logger.warning("AD-1344 PptxAgent refused: %s", refused)
                raise PermissionError(refused)
            refused = protected_write_refusal(str(target), runtime=self._runtime)  # BF-911: pptx_create
            if refused is not None:
                logger.warning("BF-911 PptxAgent refused operation=pptx_create reason_code=protected_write_refused")
                raise PermissionError(refused)
            target.parent.mkdir(parents=True, exist_ok=True)
```

**6e** (`update_xlsx`) - replaced by Amendment A1 (A1-8), re-anchored on `d2447e09`

SEARCH:
```python
            logger.warning("AD-1344 XlsxAgent refused: %s", refused)
            raise PermissionError(refused)

        workbook = load_workbook(str(source))
```
REPLACE:
```python
            logger.warning("AD-1344 XlsxAgent refused: %s", refused)
            raise PermissionError(refused)
        refused = protected_write_refusal(str(source), runtime=self._runtime)  # BF-911: xlsx_update
        if refused is not None:
            logger.warning("BF-911 XlsxAgent refused operation=xlsx_update reason_code=protected_write_refused")
            raise PermissionError(refused)

        workbook = load_workbook(str(source))
```

### Section 7: new test file

#### File `tests/test_bf911_protected_config_write_refusal.py`

```python
"""BF-911 (#1613): agents cannot rewrite the running vessel's config files or the credential vault's files.

``security.file_access.protected_write_refusal`` is the write side of BF-908's config floor. These
tests drive it directly (the forms, identity, failing closed), then through each writer that calls
it: the SWE-harness ``write_file`` and ``edit_file``, ``FileWriterAgent`` (the proposal, the write,
the consensus commit and the bundled agents' direct write) and the office document writers. The
writer tests run on a temporary layout that mirrors production: ``swe_tools._PROJECT_ROOT`` is
``<checkout>/src``, ``file_access._REPO_DEFAULT_CONFIG`` is ``<checkout>/config/system.yaml``, the
loaded ``--config`` file lies outside the checkout, and the home directory is a temporary folder
without ``.probos/config.yaml``. Each refusal is paired with a neighbour the same writer still
writes, and a copy of the config in another tree stays writable. An autouse guard snapshots the
repository's own ``config/system.yaml`` and the real ``~/.probos/config.yaml`` and compares them
after each test. The census tests pin the callers, pair them with AD-1344's, and pin that each
``commit_write`` call passes the vessel.
"""

from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from probos.agents.file_writer import FileWriterAgent
from probos.agents.utility import organizer_agents, productivity_agents
from probos.cognitive import builder_paths
from probos.cognitive.swe_harness import tools as swe_tools
from probos.cognitive.swe_harness.tools import EditFileTool, WriteFileTool
from probos.runtime import ProbOSRuntime
from probos.security import file_access
from probos.security.file_access import PROTECTED_LEAF_NAMES, protected_write_refusal
from probos.skill_framework import DocxAgent, PptxAgent, XlsxAgent
from probos.types import ConsensusOutcome, IntentMessage
from tests.test_ad1344_constitution_write_refusal import (
    _CHANNEL_SUFFIXES,
    _ShiftingPath,
    _build,
    _callee,
    _calls,
    _dir_link,
    _source,
    _tracked,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REAL_CONFIG = _REPO_ROOT / "config" / "system.yaml"
_REAL_HOME_CONFIG = Path.home() / ".probos" / "config.yaml"  # read at import, before a test moves the home directory
_BF = "BF-911"
_LIVE = "auth:\n  crew_scope_token: ''\n"
_CUSTOM = "auth:\n  crew_scope_token: ''\nsystem:\n  name: custom\n"
_CHOSEN = "auth:\n  crew_scope_token: chosen-by-the-writer\n"


# ── Fixtures and helpers ──────────────────────────────────────────────────


def _snapshot(path: Path) -> tuple[bytes, int] | None:
    try:
        return path.read_bytes(), os.stat(path).st_mode
    except FileNotFoundError:
        return None


@pytest.fixture(autouse=True)
def _real_config_files_untouched():
    """The repository's ``config/system.yaml`` and the real ``~/.probos/config.yaml`` are unchanged by each test.

    A snapshot, not a frozen hash, so the Captain's local edits are fine. The paths are literals fixed
    at import: a defect in the rule fails its own tests, not this setup.
    """
    before = (_snapshot(_REAL_CONFIG), _snapshot(_REAL_HOME_CONFIG))
    yield
    assert (_snapshot(_REAL_CONFIG), _snapshot(_REAL_HOME_CONFIG)) == before, "a real config file changed"


@pytest.fixture
def layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Production's shape under tmp_path: the SWE root is <checkout>/src, the live config <checkout>/config/system.yaml."""
    checkout = tmp_path / "checkout"
    for sub in ("src", "config", "docs", "data"):
        (checkout / sub).mkdir(parents=True)
    live = checkout / "config" / "system.yaml"
    live.write_text(_LIVE, encoding="utf-8")
    (checkout / "config" / "other.yaml").write_text("other: 1\n", encoding="utf-8")
    custom = tmp_path / "elsewhere" / "custom.yaml"
    custom.parent.mkdir()
    custom.write_text(_CUSTOM, encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    worktree = tmp_path / "worktree"
    (worktree / "config").mkdir(parents=True)
    shutil.copyfile(live, worktree / "config" / "system.yaml")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(file_access, "_REPO_DEFAULT_CONFIG", live.resolve())
    monkeypatch.setattr(swe_tools, "_PROJECT_ROOT", checkout / "src")
    assert Path.home() == home, "premise: the home directory is the temporary one"
    return SimpleNamespace(
        checkout=checkout, src=checkout / "src", live=live, custom=custom, home=home,
        home_config=home / ".probos" / "config.yaml", worktree=worktree,
        runtime=SimpleNamespace(config_path=str(custom)),
    )


def _unchanged(layout: SimpleNamespace) -> bool:
    return (
        layout.live.read_text(encoding="utf-8") == _LIVE
        and layout.custom.read_text(encoding="utf-8") == _CUSTOM
        and not layout.home_config.exists()
    )


def _link(source: Path, alias: Path) -> Path:
    try:
        os.link(source, alias)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"hard links are unavailable here: {exc}")
    assert os.path.samefile(alias, source), "premise: the alias is the same file"
    return alias


def _refused(text: str | None) -> bool:
    return text is not None and _BF in text and "\n" not in text


def _logged(caplog: pytest.LogCaptureFixture, *loggers: str) -> str:
    """The messages the named module loggers recorded; another logger may report the refusal, which names the path."""
    return "\n".join(record.getMessage() for record in caplog.records if record.name in loggers)


# ── The forms ─────────────────────────────────────────────────────────────

# Relative to the SWE root (<checkout>/src); each names <checkout>/config/system.yaml, which exists.
_LIVE_FORMS = {
    "dot-dot": "../config/system.yaml",
    "case": "../CONFIG/SYSTEM.YAML",
    "backslashes": "..\\config\\system.yaml",
    "dot-prefix": "./../config/system.yaml",
    "dot-component": "../config/./system.yaml",
    "empty-component": "..//config//system.yaml",
    "dots-only-component": "../config/.../system.yaml",
    "inner-dot-dot": "../config/sub/../system.yaml",
    "trailing-dot": "../config/system.yaml.",
    "trailing-space": "../config/system.yaml ",
    "default-stream": "../config/system.yaml::$DATA",
    "named-stream": "../config/system.yaml:hidden",
    "short-name-file": "../config/SYSTEM~1.YAM",
    "short-name-directory": "../CONFIG~1/system.yaml",
    "hfs-ignorable": "../config/sys\u200ctem.yaml",
}
# Absolute, for ~/.probos/config.yaml, which does not exist: only the name comparison can refuse.
_HOME_FORMS = {
    "exact": "{home}/.probos/config.yaml",
    "case": "{home}/.PROBOS/CONFIG.YAML",
    "backslashes": "{home}\\.probos\\config.yaml",
    "dot-dot": "{home}/.probos/notes/../config.yaml",
    "dots-only-component": "{home}/.probos/.../config.yaml",
    "trailing-dot": "{home}/.probos/config.yaml.",
    "trailing-space": "{home}/.probos/config.yaml ",
    "named-stream": "{home}/.probos/config.yaml:hidden",
    "short-name-file": "{home}/.probos/CONFIG~1.YAM",
    "hfs-ignorable": "{home}/.probos/con\u200cfig.yaml",
}
_LIVE_NEIGHBOURS = [
    "../config/other.yaml",
    "../config/system.yaml.bak",
    "../config/system.yml",
    "../config/sub/system.yaml",
    "../config",
    "config/system.yaml",
    "../docs/system.yaml",
    "../data/credential_vault.json.bak",
]
_VAULT_FORMS = [
    "../data/credential_vault.json",
    "../docs/CREDENTIAL_VAULT.JSON",
    "credential_keyring_index.json",
    "../data/credential_keyring_index.json:hidden",
    "../data/credential_vault.json.",
]
# Pure strings: judged the same on every platform, and no host is contacted.
_SAME_KEY = {
    "extended-length": ("\\\\?\\C:\\V\\config\\system.yaml", "C:/v/CONFIG/system.yaml"),
    "device-lowercase-drive": ("\\\\.\\C:\\V\\config\\system.yaml", "c:\\v\\config\\system.yaml"),
    "unc-extended": ("\\\\?\\UNC\\server\\share\\cfg\\system.yaml", "//SERVER/share/cfg/./system.yaml"),
    "unc": ("\\\\server\\share\\cfg\\system.yaml", "//server/SHARE/cfg/system.yaml"),
    "posix-dot-dot": ("/home/x/.probos/config.yaml", "/home/x/.probos/notes/../config.yaml"),
}
_OTHER_KEY = {
    "another-drive": ("C:/v/config/system.yaml", "D:/v/config/system.yaml"),
    "unc-vs-posix": ("//server/share/cfg/system.yaml", "/server/share/cfg/system.yaml"),
    "drive-vs-posix": ("C:/v/config/system.yaml", "/v/config/system.yaml"),
    "another-name": ("C:/v/config/system.yaml", "C:/v/config/system.yaml.bak"),
}


# ── 1. The rule ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("form", list(_LIVE_FORMS))
def test_rule_refuses_every_form_of_the_live_config(layout: SimpleNamespace, form: str) -> None:
    """T1: relative to the SWE root, as write_file receives them."""
    path = _LIVE_FORMS[form]
    refusal = protected_write_refusal(path, root=layout.src)
    assert _refused(refusal) and repr(path) in refusal


@pytest.mark.parametrize("form", list(_HOME_FORMS))
def test_rule_refuses_every_form_of_an_absent_home_config(layout: SimpleNamespace, form: str) -> None:
    """T2: no file to compare identity with, so the name comparison alone refuses."""
    assert not layout.home_config.exists(), "premise: ~/.probos/config.yaml is absent"
    path = _HOME_FORMS[form].format(home=layout.home)
    assert _refused(protected_write_refusal(path))
    assert _refused(protected_write_refusal(".probos/config.yaml", root=layout.home))  # relative: the resolved form decides


@pytest.mark.parametrize("path", _LIVE_NEIGHBOURS)
def test_rule_allows_the_neighbours(layout: SimpleNamespace, path: str) -> None:
    """T3."""
    assert protected_write_refusal(path, root=layout.src, runtime=layout.runtime) is None


@pytest.mark.parametrize("path", _VAULT_FORMS)
def test_rule_refuses_the_vault_file_names_anywhere(layout: SimpleNamespace, path: str) -> None:
    """T4."""
    assert PROTECTED_LEAF_NAMES == frozenset({"credential_vault.json", "credential_keyring_index.json"})
    refusal = protected_write_refusal(path, root=layout.src)
    assert _refused(refusal) and "credential vault" in refusal


def test_rule_refuses_the_loaded_config_through_the_runtime(layout: SimpleNamespace) -> None:
    """T5."""
    assert layout.custom.resolve() in file_access.protected_config_files(layout.runtime)
    assert layout.custom.resolve() not in file_access.protected_config_files(None), "premise: only the runtime names it"
    for path, root in ((str(layout.custom), None), ("custom.yaml", layout.custom.parent),
                       (str(layout.custom.parent / "CUSTOM.YAML"), None)):
        assert _refused(protected_write_refusal(path, root=root, runtime=layout.runtime)), path


def test_rule_allows_a_copy_of_the_config_in_another_tree(layout: SimpleNamespace) -> None:
    """T6."""
    copy = layout.worktree / "config" / "system.yaml"
    assert copy.read_bytes() == layout.live.read_bytes(), "premise: the same content in another file"
    assert protected_write_refusal(str(copy), runtime=layout.runtime) is None
    assert protected_write_refusal("config/system.yaml", root=layout.worktree, runtime=layout.runtime) is None


@pytest.mark.parametrize("pair", list(_SAME_KEY))
def test_rule_key_judges_lexical_forms_the_same_on_every_platform(pair: str) -> None:
    """T7."""
    left, right = _SAME_KEY[pair]
    assert file_access._write_key(left) == file_access._write_key(right)


@pytest.mark.parametrize("pair", list(_OTHER_KEY))
def test_rule_key_keeps_drives_and_names_apart(pair: str) -> None:
    """T8."""
    left, right = _OTHER_KEY[pair]
    assert not file_access._same_key(file_access._write_key(left), file_access._write_key(right))


def test_rule_refuses_a_value_that_is_not_an_exact_str_without_running_its_code(layout: SimpleNamespace) -> None:
    """T9."""
    ran: list[str] = []

    class Spy(str):
        def replace(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            ran.append("replace")
            return str.replace(self, *args, **kwargs)

        def __fspath__(self) -> str:
            ran.append("__fspath__")
            return str.__str__(self)

        def __str__(self) -> str:
            ran.append("__str__")
            return str.__str__(self)

        def __repr__(self) -> str:
            ran.append("__repr__")
            return str.__repr__(self)

    neighbour = Spy("../config/other.yaml")
    refusal = protected_write_refusal(neighbour, root=layout.src)
    assert _refused(refusal) and "exact str" in refusal
    assert ran == [], f"the rule ran code of the caller's value: {ran}"
    assert protected_write_refusal(str.__str__(neighbour), root=layout.src) is None  # control: the same text, exact str


def test_rule_refuses_a_hard_link_to_the_live_config_by_identity(layout: SimpleNamespace) -> None:
    """T10."""
    alias = _link(layout.live, layout.checkout / "docs" / "alias.yaml")
    assert _refused(protected_write_refusal("../docs/alias.yaml", root=layout.src))
    assert _refused(protected_write_refusal(str(alias)))
    (layout.checkout / "docs" / "other.yaml").write_text("x: 1\n", encoding="utf-8")
    assert protected_write_refusal("../docs/other.yaml", root=layout.src) is None  # an existing unrelated file
    assert protected_write_refusal("../docs/new.yaml", root=layout.src) is None  # not on disk


def test_rule_refuses_a_hard_link_to_the_loaded_config_through_the_runtime(layout: SimpleNamespace) -> None:
    """T11."""
    alias = _link(layout.custom, layout.checkout / "docs" / "custom-alias.yaml")
    assert _refused(protected_write_refusal(str(alias), runtime=layout.runtime))


def test_rule_checks_the_next_config_file_when_the_loaded_one_is_missing(layout: SimpleNamespace) -> None:
    """T12: the first protected file is not on disk; the hard link to the second is still found."""
    alias = _link(layout.live, layout.checkout / "docs" / "alias.yaml")
    runtime = SimpleNamespace(config_path=str(layout.checkout / "missing.yaml"))
    assert _refused(protected_write_refusal(str(alias), runtime=runtime))


def test_rule_refuses_a_directory_link_to_the_config_directory(layout: SimpleNamespace) -> None:
    """T13: through the resolved name, with the file present and with it missing."""
    _dir_link(layout.checkout / "docs" / "cfg", layout.checkout / "config")
    assert _refused(protected_write_refusal("../docs/cfg/system.yaml", root=layout.src))
    assert protected_write_refusal("../docs/cfg/other.yaml", root=layout.src) is None
    layout.live.unlink()
    assert _refused(protected_write_refusal("../docs/cfg/system.yaml", root=layout.src))


def test_rule_refuses_when_a_config_file_cannot_be_examined(
    layout: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T14."""
    assert protected_write_refusal("../docs/new.yaml", root=layout.src) is None, "premise: accepted before the patch"
    real_stat = os.stat

    def _stat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if Path(path).name == "system.yaml":
            raise PermissionError(13, "denied")
        return real_stat(path, *args, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(file_access.os, "stat", _stat)
        refusal = protected_write_refusal("../docs/new.yaml", root=layout.src)
    assert _refused(refusal) and "(config: PermissionError)" in refusal


def test_rule_refuses_when_the_target_cannot_be_examined(
    layout: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T15."""
    (layout.checkout / "docs" / "other.yaml").write_text("x: 1\n", encoding="utf-8")
    assert protected_write_refusal("../docs/other.yaml", root=layout.src) is None, "premise: accepted before the patch"
    real_stat = os.stat

    def _stat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if Path(path).name == "other.yaml":
            raise PermissionError(13, "denied")
        return real_stat(path, *args, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(file_access.os, "stat", _stat)
        refusal = protected_write_refusal("../docs/other.yaml", root=layout.src)
    assert _refused(refusal) and "(target: PermissionError)" in refusal


def test_rule_names_a_failure_under_another_metaclass_exception(
    layout: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T16: the reason reads no attribute of a class whose metaclass is not exactly ``type``."""
    ran: list[str] = []

    class Meta(type):
        @property
        def __name__(cls) -> str:  # type: ignore[override]
            ran.append("__name__")
            return "Spoofed"

    class Denied(PermissionError, metaclass=Meta):
        pass

    (layout.checkout / "docs" / "other.yaml").write_text("x: 1\n", encoding="utf-8")
    real_stat = os.stat

    def _stat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if Path(path).name == "other.yaml":
            raise Denied(13, "denied")
        return real_stat(path, *args, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(file_access.os, "stat", _stat)
        refusal = protected_write_refusal("../docs/other.yaml", root=layout.src)
    assert _refused(refusal) and "(target: Exception)" in refusal
    assert ran == [], "the metaclass's __name__ ran"


def test_rule_refuses_a_path_that_cannot_be_resolved(
    layout: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T17."""
    assert protected_write_refusal("../docs/probe.yaml", root=layout.src) is None, "premise: accepted before the patch"
    real_resolve = Path.resolve

    def resolve(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.name == "probe.yaml":
            raise ValueError("unresolvable")
        return real_resolve(self, *args, **kwargs)

    with monkeypatch.context() as patched:
        patched.setattr(Path, "resolve", resolve)
        refusal = protected_write_refusal("../docs/probe.yaml", root=layout.src)
    assert _refused(refusal) and "(resolved: ValueError)" in refusal


def test_rule_refusal_changes_nothing_on_disk_and_a_direct_write_still_works(layout: SimpleNamespace) -> None:
    """T18: no friction. The rule does not lock, chmod or mark the file; the Captain's own write is untouched."""
    before = (layout.live.read_bytes(), os.stat(layout.live).st_mode)
    assert _refused(protected_write_refusal(str(layout.live)))
    assert (layout.live.read_bytes(), os.stat(layout.live).st_mode) == before
    layout.live.write_text("auth:\n  crew_scope_token: captain\n", encoding="utf-8")
    assert layout.live.read_text(encoding="utf-8") == "auth:\n  crew_scope_token: captain\n"


@pytest.mark.parametrize("name", [".GiT", ".git. ", "fede\u200cration.md", "System.YAML", "CONFIG~1", "a b "])
def test_rule_canonical_form_is_bf894s(name: str) -> None:
    """T19: the mirrored helpers agree with builder_paths (D10)."""
    assert file_access._canonical_name(name) == builder_paths._canonical(name)
    assert file_access._SHORT_NAME.pattern == builder_paths._SHORT_NAME.pattern
    assert file_access._HFS_IGNORABLE.pattern == builder_paths._HFS_IGNORABLE.pattern


def test_rule_names_a_failure_whose_class_name_is_not_an_exact_identifier_exception(
    layout: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T36 (A1, D17): a class name with a line break, or held as a ``str`` subclass, is reported as ``Exception``.

    The reason has no line break and none of the name's code runs; ``builder_paths._exception_name`` gives
    the same name for each exception (D10 parity).
    """
    ran: list[str] = []

    class Name(str):
        def __format__(self, spec: str) -> str:
            ran.append("__format__")
            return str.__format__(self, spec)

    class TwoLines(PermissionError):
        pass

    class Formatted(PermissionError):
        pass

    TwoLines.__name__ = "Two\nLines"
    Formatted.__name__ = Name("Formatted")
    assert type(TwoLines) is type and type(Formatted.__name__) is Name, "premise: metaclass type, names as set"
    (layout.checkout / "docs" / "other.yaml").write_text("x: 1\n", encoding="utf-8")
    real_stat = os.stat
    for cls in (TwoLines, Formatted):

        def _stat(path, *args, _cls=cls, **kwargs):  # type: ignore[no-untyped-def]
            if Path(path).name == "other.yaml":
                raise _cls(13, "denied")
            return real_stat(path, *args, **kwargs)

        with monkeypatch.context() as patched:
            patched.setattr(file_access.os, "stat", _stat)
            refusal = protected_write_refusal("../docs/other.yaml", root=layout.src)
        assert _refused(refusal) and "(target: Exception)" in refusal, cls
    for exc in (TwoLines(13, "denied"), Formatted(13, "denied"), PermissionError(13, "denied")):
        assert file_access._exception_class_name(exc) == builder_paths._exception_name(exc), type(exc)
    assert ran == [], "the class name's own code ran"


# ── 2. SWE harness ────────────────────────────────────────────────────────


@pytest.mark.parametrize("form", list(_LIVE_FORMS))
async def test_write_file_refuses_every_form_of_the_live_config(layout: SimpleNamespace, form: str) -> None:
    """T20."""
    result = await WriteFileTool(layout.runtime).invoke({"path": _LIVE_FORMS[form], "content": _CHOSEN})
    assert not result.success and _BF in (result.error or "")
    assert _unchanged(layout)


async def test_write_file_refuses_each_config_by_absolute_path_and_still_writes_the_neighbours(
    layout: SimpleNamespace,
) -> None:
    """T21."""
    tool = WriteFileTool(layout.runtime)
    vault = layout.checkout / "data" / "credential_vault.json"
    for target in (layout.live, layout.custom, layout.home_config, vault):
        result = await tool.invoke({"path": str(target), "content": _CHOSEN})
        assert not result.success and _BF in (result.error or ""), target
    assert _unchanged(layout) and not vault.exists()
    worktree_config = layout.worktree / "config" / "system.yaml"
    for path, text in (("../config/other.yaml", "other: 2\n"), ("config/system.yaml", "under src\n"),
                       (str(worktree_config), _CHOSEN), (str(layout.home / ".probos" / "notes" / "n.md"), "a note\n")):
        result = await tool.invoke({"path": path, "content": text})
        assert result.success, f"{path}: {result.error}"
    assert (layout.src / "config" / "system.yaml").read_text(encoding="utf-8") == "under src\n"
    assert worktree_config.read_text(encoding="utf-8") == _CHOSEN
    assert _unchanged(layout)


async def test_write_file_refuses_a_hard_link_and_a_directory_link(layout: SimpleNamespace) -> None:
    """T22."""
    tool = WriteFileTool(layout.runtime)
    _link(layout.live, layout.checkout / "docs" / "alias.yaml")
    linked = await tool.invoke({"path": "../docs/alias.yaml", "content": _CHOSEN})
    assert not linked.success and _BF in (linked.error or "")
    _dir_link(layout.checkout / "docs" / "cfg", layout.checkout / "config")
    through = await tool.invoke({"path": "../docs/cfg/system.yaml", "content": _CHOSEN})
    assert not through.success and _BF in (through.error or "")
    assert _unchanged(layout)


async def test_write_file_refuses_under_the_effect_broker_context(layout: SimpleNamespace) -> None:
    """T23: the refusal comes before the strict-native lock and the plain write alike."""
    context = {
        "_effect_dispatch_context": object(),
        "_strict_native_target": str(layout.live),
        "_strict_native_root": str(layout.checkout),
    }
    result = await WriteFileTool(layout.runtime).invoke({"path": "../config/system.yaml", "content": _CHOSEN}, context)
    assert not result.success and _BF in (result.error or "")
    assert _unchanged(layout)


@pytest.mark.parametrize("form", list(_LIVE_FORMS))
async def test_edit_file_refuses_every_form_of_the_live_config(layout: SimpleNamespace, form: str) -> None:
    """T24."""
    result = await EditFileTool(layout.runtime).invoke(
        {"path": _LIVE_FORMS[form], "old_text": "crew_scope_token: ''", "new_text": "crew_scope_token: chosen"})
    assert not result.success and _BF in (result.error or "")
    assert _unchanged(layout)


async def test_edit_file_refuses_the_loaded_config_and_a_hard_link_and_still_edits_the_neighbours(
    layout: SimpleNamespace,
) -> None:
    """T25."""
    tool = EditFileTool(layout.runtime)
    edit = {"old_text": "crew_scope_token: ''", "new_text": "crew_scope_token: chosen"}
    loaded = await tool.invoke({"path": str(layout.custom), **edit})
    assert not loaded.success and _BF in (loaded.error or "")
    worktree_config = layout.worktree / "config" / "system.yaml"
    for path, old, new in (("../config/other.yaml", "other: 1", "other: 2"),
                           (str(worktree_config), "crew_scope_token: ''", "crew_scope_token: worktree")):
        result = await tool.invoke({"path": path, "old_text": old, "new_text": new})
        assert result.success and result.output["replacements"] == 1, f"{path}: {result.error}"
    _link(layout.live, layout.checkout / "docs" / "alias.yaml")
    linked = await tool.invoke({"path": "../docs/alias.yaml", **edit})
    assert not linked.success and _BF in (linked.error or "")
    assert _unchanged(layout)


async def test_the_swe_tools_log_a_protected_refusal_without_the_callers_path(
    layout: SimpleNamespace, caplog: pytest.LogCaptureFixture,
) -> None:
    """T37 (A1, D16): the BF-911 log line carries the operation and the reason code, not the caller's path.

    Driven with the strict effect context and without it, as AD-1344's T37; the returned error still names the path.
    """
    caplog.set_level("WARNING", logger=swe_tools.__name__)
    sentinel = "../config/SENTINEL_PRIVATE_DIR/../system.yaml"
    edit = {"old_text": "crew_scope_token: ''", "new_text": "crew_scope_token: chosen"}
    for context in ({"_effect_dispatch_context": object()}, None):
        written = await WriteFileTool(layout.runtime).invoke({"path": sentinel, "content": _CHOSEN}, context)
        edited = await EditFileTool(layout.runtime).invoke({"path": sentinel, **edit}, context)
        for result in (written, edited):
            assert not result.success and _BF in (result.error or ""), context
            assert "SENTINEL_PRIVATE_DIR" in (result.error or ""), "the returned error keeps the path"
    logged = _logged(caplog, swe_tools.__name__)
    assert "SENTINEL_PRIVATE_DIR" not in logged
    assert "operation=write_file reason_code=protected_write_refused" in logged
    assert "operation=edit_file reason_code=protected_write_refused" in logged
    assert _unchanged(layout)


async def test_the_swe_tools_judge_the_one_conversion_of_the_callers_path(layout: SimpleNamespace) -> None:
    """T38 (A1, D15): BF-911 judges ``path_text``, the text the tool resolves, writes and returns.

    The caller's ``__str__`` gives a neighbour first and the live config afterwards (AD-1344's ``_ShiftingPath``).
    """
    neighbour, live = "../config/other.yaml", "../config/system.yaml"
    written = _ShiftingPath(neighbour, live)
    result = await WriteFileTool(layout.runtime).invoke({"path": written, "content": "other: 2\n"})
    assert result.success, result.error
    assert written.conversions == 1 and result.output["path"] == neighbour
    edited = _ShiftingPath(neighbour, live)
    result = await EditFileTool(layout.runtime).invoke({"path": edited, "old_text": "other: 2", "new_text": "other: 3"})
    assert result.success, result.error
    assert edited.conversions == 1 and result.output == {"replacements": 1, "path": neighbour}
    assert (layout.checkout / "config" / "other.yaml").read_text(encoding="utf-8") == "other: 3\n"
    assert _unchanged(layout)


async def test_an_exception_from_the_rule_enters_the_swe_tools_existing_handlers(
    layout: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T39 (A1, D16): the call is a statement of each tool's existing ``try``.

    A ``LookupError`` is not a ``FileNotFoundError`` (``edit_file``'s first arm), so each tool takes its
    ``except Exception``: an error result without the effect dispatch context, the exception itself with it.
    Nothing is written.
    """

    def _raise(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise LookupError("the rule failed")

    monkeypatch.setattr(swe_tools, "protected_write_refusal", _raise)
    write = {"path": "../config/other.yaml", "content": "other: 2\n"}
    edit = {"path": "../config/other.yaml", "old_text": "other: 1", "new_text": "other: 2"}
    written = await WriteFileTool(layout.runtime).invoke(write)
    edited = await EditFileTool(layout.runtime).invoke(edit)
    assert (written.error or "").startswith("write_file failed: "), written.error
    assert (edited.error or "").startswith("edit_file failed: "), edited.error
    for tool, params in ((WriteFileTool(layout.runtime), write), (EditFileTool(layout.runtime), edit)):
        with pytest.raises(LookupError):
            await tool.invoke(params, {"_effect_dispatch_context": object()})
    assert (layout.checkout / "config" / "other.yaml").read_text(encoding="utf-8") == "other: 1\n"
    assert _unchanged(layout)


# ── 3. FileWriterAgent and its callers ────────────────────────────────────


async def test_file_writer_refuses_the_proposal_and_the_commit(layout: SimpleNamespace) -> None:
    """T26."""
    agent = FileWriterAgent(pool="filesystem", runtime=layout.runtime)
    await agent.start()
    for target in (layout.live, layout.custom):
        proposal = await agent.handle_intent(IntentMessage(intent="write_file", params={"path": str(target), "content": _CHOSEN}))
        assert proposal is not None and proposal.success is False and _BF in (proposal.error or ""), target
    other = layout.checkout / "config" / "other.yaml"
    control = await agent.handle_intent(IntentMessage(intent="write_file", params={"path": str(other), "content": "other: 2\n"}))
    assert control is not None and control.success is True and control.result["requires_consensus"] is True
    for target, runtime in ((layout.live, None), (layout.home_config, None), (layout.custom, layout.runtime)):
        committed = await FileWriterAgent.commit_write(str(target), _CHOSEN, runtime=runtime)
        assert committed["success"] is False and _BF in committed["error"], target
    assert (await FileWriterAgent.commit_write(str(other), "other: 2\n", runtime=layout.runtime))["success"] is True
    assert _unchanged(layout)


class _ConsensusVessel:
    """What ``submit_write_with_consensus`` reads from its runtime, with an approving quorum; the production method runs."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = str(config_path)
        self.event_log = SimpleNamespace(log=AsyncMock(return_value="row-1"))

    async def submit_intent_with_consensus(self, intent, params=None, timeout=None, **kwargs):  # type: ignore[no-untyped-def]
        return {"intent": None, "results": [], "verifications": [],
                "consensus": SimpleNamespace(outcome=ConsensusOutcome.APPROVED)}


async def test_the_consensus_commit_passes_the_vessel(layout: SimpleNamespace) -> None:
    """T27: intent -> approved -> commit_write(runtime=self) -> refused; only the runtime names this file."""
    vessel = _ConsensusVessel(layout.custom)
    refused = await ProbOSRuntime.submit_write_with_consensus(vessel, str(layout.custom), _CHOSEN)
    assert refused["committed"] is False
    assert vessel.event_log.log.await_args.kwargs["event"] == "write_failed"
    assert _unchanged(layout)
    other = layout.checkout / "config" / "other.yaml"
    allowed = await ProbOSRuntime.submit_write_with_consensus(vessel, str(other), "other: 2\n")
    assert allowed["committed"] is True and other.read_text(encoding="utf-8") == "other: 2\n"


async def test_the_bundled_agents_direct_write_cannot_reach_a_config_file(layout: SimpleNamespace) -> None:
    """T28: the notes agent joins a model-chosen filename to ~/.probos/notes; both helpers pass their runtime."""
    notes = layout.home / ".probos" / "notes"
    notes.mkdir(parents=True)
    assert not await organizer_agents._mesh_write_file(None, f"{notes}/../config.yaml", _CHOSEN)
    for module in (organizer_agents, productivity_agents):
        assert not await module._mesh_write_file(layout.runtime, str(layout.custom), _CHOSEN), module.__name__
    assert _unchanged(layout)
    assert await organizer_agents._mesh_write_file(layout.runtime, f"{notes}/note.md", "a note\n")
    assert (notes / "note.md").read_text(encoding="utf-8") == "a note\n"


# ── 4. Office document writers ────────────────────────────────────────────


async def test_office_create_refuses_the_loaded_config_and_the_home_config(layout: SimpleNamespace) -> None:
    """T29."""
    docx = DocxAgent(pool="office", runtime=layout.runtime)
    pptx = PptxAgent(pool="office", runtime=layout.runtime)
    for target in (layout.custom, layout.home_config):
        with pytest.raises(PermissionError, match=_BF):
            await docx.handle_intent(IntentMessage(intent="docx_create", params={
                "title": "Settings", "content": ["x"], "output_path": str(target)}))
        with pytest.raises(PermissionError, match=_BF):
            await pptx.handle_intent(IntentMessage(intent="pptx_create", params={
                "title": "Settings", "slides": [{"title": "x", "bullets": ["y"]}], "output_path": str(target)}))
    assert _unchanged(layout)
    notes = layout.checkout / "docs" / "notes.docx"
    control = await docx.handle_intent(IntentMessage(intent="docx_create", params={
        "title": "Notes", "content": ["x"], "output_path": str(notes)}))
    assert control is not None and control.success is True and notes.is_file()


async def test_office_revise_and_update_refuse_a_link_to_the_loaded_config(layout: SimpleNamespace) -> None:
    """T30."""
    docx_alias = _link(layout.custom, layout.checkout / "docs" / "settings.docx")
    xlsx_alias = _link(layout.custom, layout.checkout / "docs" / "settings.xlsx")
    with pytest.raises(PermissionError, match=_BF):
        await DocxAgent(pool="office", runtime=layout.runtime).handle_intent(IntentMessage(intent="docx_revise", params={
            "file_path": str(docx_alias), "instructions": "amend"}))
    with pytest.raises(PermissionError, match=_BF):
        await XlsxAgent(pool="office", runtime=layout.runtime).handle_intent(IntentMessage(intent="xlsx_update", params={
            "file_path": str(xlsx_alias), "sheet": "Sheet", "updates": {"A1": "x"}}))
    assert _unchanged(layout)
    notes = layout.checkout / "docs" / "notes.docx"
    await DocxAgent(pool="office").create_docx(title="Notes", content=["x"], output_path=str(notes))
    revised = await DocxAgent(pool="office", runtime=layout.runtime).handle_intent(IntentMessage(intent="docx_revise", params={
        "file_path": str(notes), "instructions": "tidy"}))
    assert revised is not None and revised.success is True


async def test_the_other_writers_log_a_protected_refusal_without_the_callers_path(
    layout: SimpleNamespace, caplog: pytest.LogCaptureFixture,
) -> None:
    """T40 (A1, D16): FileWriterAgent's and the office writers' BF-911 log lines carry the operation and the reason code.

    Each target is its writer's loaded config file (its runtime's ``config_path``) in a directory named
    SENTINEL_PRIVATE_DIR, so the name comparison refuses it with no link; the returned or raised refusal names the path.
    """
    loggers = (FileWriterAgent.__module__, DocxAgent.__module__)
    for name in loggers:
        caplog.set_level("WARNING", logger=name)
    private = layout.checkout / "SENTINEL_PRIVATE_DIR"
    private.mkdir()
    targets = {suffix: private / f"settings{suffix}" for suffix in (".yaml", ".docx", ".xlsx")}
    for target in targets.values():
        target.write_bytes(b"settings")
    vessels = {suffix: SimpleNamespace(config_path=str(target)) for suffix, target in targets.items()}
    writer = FileWriterAgent(pool="filesystem", runtime=vessels[".yaml"])
    await writer.start()
    proposal = await writer.handle_intent(IntentMessage(intent="write_file", params={"path": str(targets[".yaml"]), "content": _CHOSEN}))
    assert proposal is not None and proposal.success is False and "SENTINEL_PRIVATE_DIR" in (proposal.error or "")
    committed = await FileWriterAgent.commit_write(str(targets[".yaml"]), _CHOSEN, runtime=vessels[".yaml"])
    assert committed["success"] is False and "SENTINEL_PRIVATE_DIR" in committed["error"]
    docx = DocxAgent(pool="office", runtime=vessels[".docx"])
    calls = (
        (docx, "docx_create", {"title": "Settings", "content": ["x"], "output_path": str(targets[".docx"])}),
        (PptxAgent(pool="office", runtime=vessels[".yaml"]), "pptx_create", {
            "title": "Settings", "slides": [{"title": "x", "bullets": ["y"]}], "output_path": str(targets[".yaml"])}),
        (docx, "docx_revise", {"file_path": str(targets[".docx"]), "instructions": "amend"}),
        (XlsxAgent(pool="office", runtime=vessels[".xlsx"]), "xlsx_update", {
            "file_path": str(targets[".xlsx"]), "sheet": "Sheet", "updates": {"A1": "x"}}),
    )
    for agent, intent, params in calls:
        with pytest.raises(PermissionError, match=_BF) as raised:
            await agent.handle_intent(IntentMessage(intent=intent, params=params))
        assert "SENTINEL_PRIVATE_DIR" in str(raised.value), intent
    logged = _logged(caplog, *loggers)
    assert "SENTINEL_PRIVATE_DIR" not in logged
    for operation in ("propose_write", "commit_write", "docx_create", "pptx_create", "docx_revise", "xlsx_update"):
        assert f"operation={operation} reason_code=protected_write_refused" in logged, operation
    assert all(target.read_bytes() == b"settings" for target in targets.values())
    assert _unchanged(layout)


# ── 5. The builder is unchanged ───────────────────────────────────────────


async def test_a_build_still_edits_a_worktrees_config(layout: SimpleNamespace) -> None:
    """T31: BF-897 keeps a build out of the running checkout, so its config/system.yaml is another file."""
    assert _refused(protected_write_refusal(str(layout.live))), "premise: the live config is protected in this layout"
    change = {"path": "config/system.yaml", "mode": "modify",
              "replacements": [{"search": "crew_scope_token: ''", "replace": "crew_scope_token: build"}]}
    result, commit = await _build(layout.worktree, [change])
    assert not result.error, result.error
    assert (layout.worktree / "config" / "system.yaml").read_text(encoding="utf-8") == "auth:\n  crew_scope_token: build\n"
    assert "config/system.yaml" in commit.await_args.args[0]
    assert _unchanged(layout)


# ── 6. The inventory (AST censuses over tracked files) ────────────────────

_RULE = "protected_write_refusal"
_RULE_HELPERS = frozenset({"_write_key", "_same_key"})
_CENSUS_NAMES = frozenset({_RULE, "constitution_write_refusal", "commit_write", *_RULE_HELPERS})
_EXPECTED_CALLERS = {
    ("src/probos/cognitive/swe_harness/tools.py", "WriteFileTool.invoke"),
    ("src/probos/cognitive/swe_harness/tools.py", "EditFileTool.invoke"),
    ("src/probos/agents/file_writer.py", "FileWriterAgent.act"),
    ("src/probos/agents/file_writer.py", "FileWriterAgent.commit_write"),
    ("src/probos/skill_framework.py", "DocxAgent.create_docx"),
    ("src/probos/skill_framework.py", "DocxAgent.revise_docx"),
    ("src/probos/skill_framework.py", "PptxAgent.create_pptx"),
    ("src/probos/skill_framework.py", "XlsxAgent.update_xlsx"),
}
# The one caller of AD-1344's rule that does not call this one, and why (D6).
_BUILDER_ONLY = {
    ("src/probos/cognitive/builder_paths.py", "builder_write_refusal"):
        "a build runs in a linked worktree (BF-897 operator_checkout_refusal), whose config/system.yaml is another file",
}
_COMMIT_WRITE_CALLERS = {
    ("src/probos/runtime.py", "ProbOSRuntime.submit_write_with_consensus"),
    ("src/probos/agents/utility/organizer_agents.py", "_mesh_write_file"),
    ("src/probos/agents/utility/productivity_agents.py", "_mesh_write_file"),
}


@lru_cache(maxsize=1)
def _call_sites() -> dict[str, frozenset[tuple[str, str, bool]]]:
    """(file, function, passes runtime=) for each call of a census name in the tracked source."""
    sites: dict[str, set[tuple[str, str, bool]]] = {}
    for rel in _tracked("src/probos"):
        if not rel.endswith(".py"):
            continue
        for scope, call in _calls(_source(rel)):
            name = _callee(call)
            if name in _CENSUS_NAMES:
                passes_runtime = any(keyword.arg == "runtime" for keyword in call.keywords)
                sites.setdefault(name, set()).add((rel, scope, passes_runtime))
    return {name: frozenset(found) for name, found in sites.items()}


def _functions(name: str) -> set[tuple[str, str]]:
    return {(rel, scope) for rel, scope, _ in _call_sites().get(name, frozenset())}


def test_census_callers_are_the_inventoried_writers_and_the_helpers_stay_private() -> None:
    """T32."""
    assert _functions(_RULE) == _EXPECTED_CALLERS
    helper_files = {rel for name in _RULE_HELPERS for rel, _ in _functions(name)}
    assert helper_files == {"src/probos/security/file_access.py"}


def test_census_every_caller_of_ad1344s_rule_but_the_builder_calls_this_one() -> None:
    """T33: a writer that gains AD-1344's guard (its census B asks for one) must gain this one too."""
    constitution = _functions("constitution_write_refusal")
    assert set(_BUILDER_ONLY) <= constitution, "premise: the builder boundary calls AD-1344's rule"
    assert constitution - set(_BUILDER_ONLY) == _functions(_RULE)


def test_census_every_commit_write_call_passes_the_vessel() -> None:
    """T34."""
    sites = _call_sites().get("commit_write", frozenset())
    assert {(rel, scope) for rel, scope, _ in sites} == _COMMIT_WRITE_CALLERS
    assert all(passes for _, _, passes in sites), sorted(sites)


def test_census_the_captains_channels_do_not_consult_the_rule() -> None:
    """T35: no tracked script, hook or workflow with a suffix in ``_CHANNEL_SUFFIXES`` names the rule (no friction)."""
    channels = [rel for rel in _tracked("scripts", ".github", ".githooks", ".pre-commit-config.yaml")
                if rel.endswith(_CHANNEL_SUFFIXES)]
    assert any(rel.startswith(".github/workflows/") for rel in channels), "premise: CI is tracked and scanned"
    for rel in channels:
        assert _RULE not in (_REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace"), rel
```

---

## Tests (map)

| T | What it pins | Writer | POSIX outcome |
|---|---|---|---|
| T1 | 15 forms of the existing live file, relative to the SWE root | rule | same: the key normalises every form; resolution follows a link on both |
| T2 | 10 forms of the absent home config | rule | same: pure key comparison |
| T3 | Neighbours, including `config/system.yaml` under `src` and the `config` directory | rule | same |
| T4 | Vault names anywhere, with case, stream and trailing-dot forms | rule | same |
| T5 | The loaded `--config` file through the runtime | rule | same |
| T6 | A worktree copy with identical content stays writable | rule | same |
| T7–T8 | `\\?\`, `\\.\`, `\\?\UNC\`, UNC, drive case, `..`; drives and names kept apart | `_write_key`, `_same_key` | same: pure strings, no host contacted |
| T9 | A non-exact `str` is refused; none of its code runs | rule | same |
| T10–T13 | Hard link to the live and the loaded file; the next file checked when the loaded one is missing; a directory link, with the file present and missing | rule | same; skips where the host cannot make a link (Windows: a junction needs no privilege; ubuntu: hard links and symlinks) |
| T14–T17 | Failing closed: unexaminable config, unexaminable target, metaclass-safe naming, resolution failure | rule | same (`os.stat` patched by name; `pathlib`'s own `stat` swallows the injected `PermissionError`, as in S1 T13–T15) |
| T18 | No friction | — | same |
| T19 | Parity with BF-894's canonical form | — | same |
| T20–T23 | `write_file`: 15 forms, absolute paths of all three configs and the vault, neighbours (a worktree copy, `src/config/system.yaml`, a note under `~/.probos`), hard and directory link, effect-broker context | SWE | same outcome. A mutant that removes the check writes a different file on each OS (for example `system.yaml:hidden` is a stream on NTFS and a file on ext4), always under `tmp_path` |
| T24–T25 | `edit_file`: 15 forms, the loaded file, a hard link, neighbours | SWE | same |
| T26 | `FileWriterAgent` proposal (with its runtime) and `commit_write` with and without `runtime=` | `FileWriterAgent` | same |
| T27 | Consensus commit: `submit_write_with_consensus` passes `self` | `ProbOSRuntime` (production method, stub self) | same |
| T28 | Bundled agents: `notes/../config.yaml` and the loaded file through both `_mesh_write_file` | bundled | same |
| T29–T30 | `docx_create`, `pptx_create` (loaded and home config); `docx_revise`, `xlsx_update` on hard links to the loaded file; neighbours | office | same; T30 skips without hard links |
| T31 | A build still edits a worktree's `config/system.yaml` | `execute_approved_build` | same |
| T32–T35 | Census: callers; pairing with AD-1344; `commit_write` passes `runtime=`; the Captain's channels | — | same; skips without git |
| T36 | A class name with a line break, or held as a `str` subclass, is reported as `Exception`; the reason has no line break; none of the name's code runs; the two helpers agree | rule | same |
| T37 | `write_file`/`edit_file` log `operation=… reason_code=protected_write_refused` and no caller path, with and without the strict effect context; the returned error names the path | SWE | same |
| T38 | A path whose `__str__` gives a neighbour, then the live config: one conversion; the neighbour is written, edited and returned; the live file is unchanged | SWE | same |
| T39 | A `LookupError` from the rule takes each SWE tool's `except Exception`: an error result without the dispatch context, re-raised with it; nothing written | SWE | same |
| T40 | `FileWriterAgent` (proposal, write) and the four office writers log the operation and the reason code and no caller path; the refusal names the path | `FileWriterAgent`, office | same: no link needed |

A mutant whose only killer skipped counts as **not run**, not killed. The campaign host (win32 NTFS) makes both link kinds.

---

## Milestones (about 50 Builder tool calls each)

| M | Scope | Focused checks (`-n 0`; never `pytest tests/`) |
|---|---|---|
| **M1** | Section 1; write the whole of Section 7's file | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf911_protected_config_write_refusal.py -v -n 0 -k "test_rule_"`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf908_floor_and_children.py tests/test_bf908_crew_scope_token.py tests/test_bf758_file_read_confinement.py tests/test_ad1200_instruction_file_access.py -q -n 0`; `d:/ProbOS/.venv/Scripts/python.exe -c "import probos.security.file_access, probos.execution.workspace, probos.runtime"`. Cut: local commit `BF-911 M1: the protected-file write rule`. |
| **M2** | Sections 2–6 | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf911_protected_config_write_refusal.py -v -n 0 -k "not test_rule_ and not test_census_"`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1344_constitution_write_refusal.py tests/test_ad544_native_tools.py tests/test_ad1316_real_effect_routes.py tests/test_ad1316_governed_effect_broker.py tests/test_ad1179_tool_schema_golden.py tests/test_file_writer.py tests/test_utility_agents.py tests/test_ad838_office_create_wiring.py tests/test_skill_framework.py tests/test_ad1284_consensus_gate_reachability.py tests/test_consensus_integration.py tests/test_ad1021b_workspace_write.py tests/test_ad741_config_api.py -q -n 0`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf894_builder_write_boundary.py tests/test_builder_guardrails.py tests/test_bf897_build_pipeline_scale_and_checkout.py tests/test_bf898_fix_loop_grader_protection.py -q -n 0`; `d:/ProbOS/.venv/Scripts/python.exe -c "import probos.security.file_access, probos.cognitive.swe_harness.tools, probos.agents.file_writer, probos.agents.utility.organizer_agents, probos.agents.utility.productivity_agents, probos.skill_framework, probos.runtime"`. Cut: local commit `BF-911 M2: the agent-reachable writers call the rule; commit_write takes the vessel`. |
| **M3** | Census tests green, the mutation campaign, Section 8, the ledger, the section audit (each Section maps to code, each T to a test) | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf911_protected_config_write_refusal.py -v -n 0`; `d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check`; `d:/ProbOS/.venv/Scripts/python.exe scripts/check_seam_contracts.py`; `d:/ProbOS/.venv/Scripts/python.exe scripts/check_store_registry.py --check`; `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1184_ad_ledger.py tests/test_ad1343_seam_registry.py -q -n 0`. Cut: local commit `BF-911 M3: census and trackers`. |

**Census rule for the Builder (M3).** If T33 reports a function that calls AD-1344's rule and not this one, add the BF-911 call there only when the path comes from an intent or tool parameter, and **stop** to report it either way: a new caller is an inventory change for the Architect. The broad gate is the main session's.

**Interpreter note.** The venv's `probos` is an editable install of `D:\ProbOS\src`. In a worktree, run with `PYTHONPATH=<worktree>\src;<worktree>` as the orchestrator's probe did, or the tests import the main checkout's code.

---

## Mutation table (run once on the final tree; every anchor is a whole, unique, stripped line)

Apply one mutant at a time, run the named tests at `-n 0`, restore. **Campaign of record:** record the tree SHA and the sha256 of `security/file_access.py`, `swe_harness/tools.py`, `agents/file_writer.py`, `runtime.py`, `agents/utility/organizer_agents.py`, `agents/utility/productivity_agents.py`, `skill_framework.py`, `tests/test_bf911_protected_config_write_refusal.py` and `tests/test_ad1344_constitution_write_refusal.py`. A later Builder whose hashes match does not repeat it; if one file differs, rerun only that file's rows.

**AD-1344 S1's campaign.** S1's record (`DECISIONS.md:466`, 56 of 56) pins the sha256 of `swe_harness/tools.py`, `agents/file_writer.py` and `skill_framework.py`, which BF-911 changes. Rerun S1's 24 rows on those files on BF-911's tree, against S1's unchanged test file: `tools.py` S1-W1–W4 (A1-re-anchored), S1-W13–W18, S1-W19, S1-W19b, S1-W20, S1-W20b, S1-W21, S1-W22; `file_writer.py` S1-W5–W7; `skill_framework.py` S1-W8–W12. S1's other 32 rows (B, S and H) mutate files outside BF-911's diff, and S1's test file is unchanged, so S1's record stands for them.

| ID | File | Line (stripped) → mutant | Killed by |
|---|---|---|---|
| R1 | file_access | `if type(path) is not str:` → `if False:` | T9 |
| R2 | file_access | `target = Path(root) / target` → `pass` | T1[dot-dot] |
| R3 | file_access | `return _protected_unverifiable(path, "resolved", exc)` → `return None` | T17 |
| R4 | file_access | `key = _write_key(str(resolved))` → `key = _write_key(path)` | T2, T13 (T1 rows are rescued by identity, since the live file exists) |
| R5 | file_access | `if key[-1] in _PROTECTED_LEAF_KEYS:` → `if False:` | T4 |
| R6 | file_access | `configs = protected_config_files(runtime)` → `configs = protected_config_files(None)` | T5 |
| R7 | file_access | `if any(_same_key(key, _write_key(str(config))) for config in configs):` → `if False:` | T2 |
| R8 | file_access | `continue  # not on disk: the name comparison above is the whole check` → `return None` | T12 |
| R9 | file_access | `return _protected_unverifiable(path, "config", exc)` → `continue` | T14 |
| R10 | file_access | `return _protected_unverifiable(path, "target", exc)` → `return None` | T15 |
| R11 | file_access | `if os.path.samestat(current, config_stat):` → `if False:` | T10, T11 |
| R12 | file_access | `if type(cls) is not type:` → `if False:` | T16 |
| R13 | file_access | `return name if type(name) is str and name.isidentifier() else "Exception"` → `return "Exception"` | T14 |
| R15 | file_access | same line → `return name if name.isidentifier() else "Exception"` | T36 |
| R16 | file_access | same line → `return name if type(name) is str else "Exception"` | T36 |
| R14 | file_access | `_PROTECTED_LEAF_KEYS = frozenset(_canonical_name(name) for name in PROTECTED_LEAF_NAMES)` → `_PROTECTED_LEAF_KEYS = frozenset()` | T4 |
| K1 | file_access | `unified = path_text.replace("\\", "/")` → `unified = path_text` | T7[extended-length] |
| K2 | file_access | `if unified[:4] in _DEVICE_PREFIXES:` → `if False:` | T7[extended-length] |
| K3 | file_access | `if unified[:4].upper() == "UNC/":` → `if False:` | T7[unc-extended] |
| K4 | file_access | `drive, rest = ntpath.splitdrive(unified)` → `drive, rest = "", unified` | T8[unc-vs-posix] |
| K5 | file_access | `return (drive.upper(), *(name for name in names if name))` → `return (drive, *(name for name in names if name))` | T7[device-lowercase-drive] |
| K6 | file_access | same line → `return (drive.upper(), *names)` | T2[dots-only-component] |
| K7 | file_access | `names = [_canonical_name(part.split(":", 1)[0]) for part in posixpath.normpath(rest or "/").split("/")]` → `names = [_canonical_name(part) for part in posixpath.normpath(rest or "/").split("/")]` | T2[named-stream] |
| K8 | file_access | same line → `names = [_canonical_name(part.split(":", 1)[0]) for part in (rest or "/").split("/")]` | T7[posix-dot-dot] |
| K9 | file_access | `return _HFS_IGNORABLE.sub("", part).rstrip(" .").upper()` → `return part.upper()` | T19, T2[trailing-dot] |
| K10 | file_access | `return len(candidate) == len(protected) and all(` → `return all(` | T3[../config] |
| K11 | file_access | `name == expected or (_SHORT_NAME.search(name) is not None and name[:2] == expected[:2])` → `name == expected` | T2[short-name-file] |
| W1 | tools.py | `refused = protected_write_refusal(path_text, root=_PROJECT_ROOT, runtime=self._runtime)  # BF-911: write_file` → `refused = None` | T20, T21 |
| W2 | tools.py | same line → `refused = protected_write_refusal(path_text, root=None, runtime=self._runtime)  # BF-911: write_file` | T20[dot-dot] |
| W3 | tools.py | same line → `refused = protected_write_refusal(path_text, root=_PROJECT_ROOT, runtime=None)  # BF-911: write_file` | T21 |
| W4 | tools.py | `refused = protected_write_refusal(path_text, root=_PROJECT_ROOT, runtime=self._runtime)  # BF-911: edit_file` → `refused = None` | T24 |
| W5 | tools.py | same line → `refused = protected_write_refusal(path_text, root=None, runtime=self._runtime)  # BF-911: edit_file` | T24[dot-dot] |
| W6 | tools.py | same line → `refused = protected_write_refusal(path_text, root=_PROJECT_ROOT, runtime=None)  # BF-911: edit_file` | T25 |
| W22 | tools.py | W1's line → `refused = protected_write_refusal(str(path), root=_PROJECT_ROOT, runtime=self._runtime)  # BF-911: write_file` | T38 |
| W23 | tools.py | W4's line → `refused = protected_write_refusal(str(path), root=_PROJECT_ROOT, runtime=self._runtime)  # BF-911: edit_file` | T38 |
| W7 | file_writer | `refused = protected_write_refusal(str(p), runtime=self._runtime)  # BF-911: the proposal` → `refused = None` | T26 |
| W8 | file_writer | same line → `refused = protected_write_refusal(str(p), runtime=None)  # BF-911: the proposal` | T26 |
| W9 | file_writer | `refused = protected_write_refusal(str(p), runtime=runtime)  # BF-911: the write` → `refused = None` | T26, T28 |
| W10 | file_writer | same line → `refused = protected_write_refusal(str(p), runtime=None)  # BF-911: the write` | T26, T27, T28 |
| W11 | runtime.py | `commit_result = await FileWriterAgent.commit_write(path, content, runtime=self)  # BF-911: the loaded config file too` → `commit_result = await FileWriterAgent.commit_write(path, content)` | T27 |
| W12 | organizer_agents | `result = await FileWriterAgent.commit_write(path, content, runtime=runtime)  # BF-911: the loaded config file too` → `result = await FileWriterAgent.commit_write(path, content)` | T28 |
| W13 | productivity_agents | the same line → the same mutant | T28 |
| W14 | skill_framework | `refused = protected_write_refusal(str(target), runtime=self._runtime)  # BF-911: docx_create` → `refused = None` | T29 |
| W15 | skill_framework | same line → `… runtime=None)  # BF-911: docx_create` | T29 |
| W16 | skill_framework | `refused = protected_write_refusal(str(target), runtime=self._runtime)  # BF-911: pptx_create` → `refused = None` | T29 |
| W17 | skill_framework | same line → `… runtime=None)  # BF-911: pptx_create` | T29 |
| W18 | skill_framework | `refused = protected_write_refusal(str(source), runtime=self._runtime)  # BF-911: docx_revise` → `refused = None` | T30 |
| W19 | skill_framework | same line → `… runtime=None)  # BF-911: docx_revise` | T30 |
| W20 | skill_framework | `refused = protected_write_refusal(str(source), runtime=self._runtime)  # BF-911: xlsx_update` → `refused = None` | T30 |
| W21 | skill_framework | same line → `… runtime=None)  # BF-911: xlsx_update` | T30 |
| L1 | tools.py | `logger.warning("BF-911 WriteFileTool refused operation=write_file reason_code=protected_write_refused")` → `logger.warning("BF-911 WriteFileTool refused: %s", refused)` | T37 |
| L1b | tools.py | same line → `pass` | T37 |
| L2 | tools.py | `logger.warning("BF-911 EditFileTool refused operation=edit_file reason_code=protected_write_refused")` → `logger.warning("BF-911 EditFileTool refused: %s", refused)` | T37 |
| L2b | tools.py | same line → `pass` | T37 |
| L3 | file_writer | `logger.warning("BF-911 FileWriterAgent refused operation=propose_write reason_code=protected_write_refused")` → `logger.warning("BF-911 FileWriterAgent proposal refused: %s", refused)` | T40 |
| L3b | file_writer | same line → `pass` | T40 |
| L4 | file_writer | `logger.warning("BF-911 FileWriterAgent refused operation=commit_write reason_code=protected_write_refused")` → `logger.warning("BF-911 FileWriterAgent write refused: %s", refused)` | T40 |
| L4b | file_writer | same line → `pass` | T40 |
| L5 | skill_framework | `logger.warning("BF-911 DocxAgent refused operation=docx_create reason_code=protected_write_refused")` → `logger.warning("BF-911 DocxAgent refused: %s", refused)` | T40 |
| L5b | skill_framework | same line → `pass` | T40 |
| L6 | skill_framework | `logger.warning("BF-911 DocxAgent refused operation=docx_revise reason_code=protected_write_refused")` → `logger.warning("BF-911 DocxAgent refused: %s", refused)` | T40 |
| L6b | skill_framework | same line → `pass` | T40 |
| L7 | skill_framework | `logger.warning("BF-911 PptxAgent refused operation=pptx_create reason_code=protected_write_refused")` → `logger.warning("BF-911 PptxAgent refused: %s", refused)` | T40 |
| L7b | skill_framework | same line → `pass` | T40 |
| L8 | skill_framework | `logger.warning("BF-911 XlsxAgent refused operation=xlsx_update reason_code=protected_write_refused")` → `logger.warning("BF-911 XlsxAgent refused: %s", refused)` | T40 |
| L8b | skill_framework | same line → `pass` | T40 |

66 rows (Amendment A1). In T29–T30 a surviving check-free writer raises a different exception or no exception, so `pytest.raises(PermissionError, match="BF-911")` fails the test body (a failure, not a setup error). Amendment A1's rows fail assertions in the test body: each L row fails on the sentinel in the module loggers' messages and each Lb row on the missing `operation=… reason_code=protected_write_refused`; W22 and W23 fail `result.success` in T38, because the second conversion is the live config; R12 fails T16's `(target: Exception)` (the metaclass's `__name__` gives `Spoofed`); R13 fails T14's `(config: PermissionError)`; R15 fails T36's `(target: Exception)` for the `str`-subclass name; R16 fails T36's no-line-break check.

Equivalent mutants, excluded with reasons:
- `if root is not None and not target.is_absolute():` → `if root is not None:`. Joining an absolute path to a root yields the absolute path.
- `return None  # not on disk, so not a second name of an existing config file` → `continue`. The next iteration stats the same missing target, and the loop ends in `return None`.

Wiring a campaign cannot reach by tests alone (verified by reading; the Diff Reviewer checks): the effect broker's dispatch into `WriteFileTool.invoke` when `effect_broker_enabled` is on (T23 drives the context the executor passes, `tools/executor.py:866`, `:870`); `register_native_swe_tools` constructing the tools with the real runtime (`swe_harness/tools.py:1396-1397`). Not pinned by a test: the `except FileNotFoundError` route in `edit_file` for an exception from the rule or a logging filter (D16, R11; by reading, `tools.py:1161-1168`).

---

## Section 8: Trackers

### `PROGRESS.md`

SEARCH:
```markdown
# ProbOS Progress

```
REPLACE:
```markdown
# ProbOS Progress

**BF-911 (2026-10-21), #1613 -- agents cannot rewrite the running vessel's config files; BF-908's config floor gains its write side.** One rule, `security.file_access.protected_write_refusal`, refuses a write with a one-line reason naming BF-911 when the resolved path names a file in `protected_config_files(runtime)` (the loaded `--config` file, the checkout's `config/system.yaml`, `~/.probos/config.yaml`), present or absent, or a credential vault file name; the comparison is per component in BF-894's canonical form (case, separators, `..`, stream suffixes, trailing dots and spaces, 8.3 short forms, `\\?\` and UNC prefixes). An existing file with the `os.stat` identity of an existing protected config file (a hard link), a value that is not an exact `str` and a path it cannot examine are refused too. The callers: the SWE-harness `write_file` and `edit_file`, `FileWriterAgent` (the proposal and the write; `commit_write` takes the vessel as `runtime=`, passed by the consensus commit and by the bundled agents' direct write) and the office writers `docx_create`, `docx_revise`, `pptx_create` and `xlsx_update`. A file at another path, such as a build worktree's `config/system.yaml`, stays writable; the builder boundary is unchanged. Census tests in `tests/test_bf911_protected_config_write_refusal.py` pin the callers, pair them with AD-1344's and pin that each `commit_write` call passes the vessel. Shell and code execution stay outside, as for AD-1344. No config field.

```

### `DECISIONS.md` (insert before the heading that follows the newest entry of the recent run; on `d2447e09` AD-1344 S1's entry, `:455`, with its Amendment A1 bullet `:463` and its campaign bullet `:466`, precedes it at `:469`)

SEARCH:
```markdown
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
### BF-911 -- Agents cannot rewrite the running vessel's config files: the write side of BF-908's floor, called by the agent-reachable writers (2026-10-21, #1613)

- *Scope.* The config files `protected_config_files(runtime)` names and the credential vault's file names. Contract: `prompts/bf-911-protected-config-write-refusal.md` (option A of the Architect's ruling on #1613).
- *D1/D2 (home and set).* `security.file_access.protected_write_refusal`, beside `protected_config_files`, so the read and write sides read one list. Absent files are refused by name: creating `~/.probos/config.yaml` changes which file a start without `--config` loads.
- *D3 (matching).* The resolved path, per component in BF-894's canonical form (helpers mirrored in `security`, parity pinned), against each protected file; then `os.stat` identity with each existing one; vault names on the resolved last component. A copy at another path stays writable.
- *D4 (the runtime).* Each writer passes the runtime it holds; `FileWriterAgent.commit_write` gains a keyword-only `runtime`, passed by `submit_write_with_consensus` and both `_mesh_write_file`. Without a runtime the checkout default and `~/.probos/config.yaml` are still refused.
- *D5/D6.* Each call follows AD-1344's call in the same writer. The builder boundary is unchanged: BF-897 keeps a build in a linked worktree, whose config is another file.
- *D15-D17 (after AD-1344 S1's Amendment A1).* In the SWE tools the call judges `path_text`, S1's one conversion of the caller's path (T38). Each BF-911 log line is a constant naming the operation and the reason code `protected_write_refused`, the same with and without the strict effect context; the returned or raised refusal still names the path (T37, T40). An exception class name enters a reason when it is an exact-`str` identifier, else `Exception`, as in S1's helper (T36). For the writers listed, this answers S1's residual that BF-908's read floor had no write-side sibling.
- *Rejected.* Generalising AD-1344's rule (a Captain-document rule mixed with a credential rule, no runtime); refusing only edits of `auth.crew_scope_token` (fragile, leaves the other settings open); a keyring-only token (changes the credential model; deferred); a boot-time registration of the loaded file (module state, global lookup); a lock or mode change (friction).
- *Residuals (numbered on #1523 by the orchestrator).* Shell and code execution; MCP servers and agent-designed code; check-then-write is not atomic outside the Windows strict-native path; the data directory is not on the write floor and the vault is refused by name only; a writer without a runtime does not know a `--config` file outside the defaults; a relative `--config` resolves against the working directory at check time; a link to the live config placed inside a build worktree; over-refusal of 8.3-shaped names and of case variants on case-sensitive filesystems; the census bounds; AD-1344's refusal log lines in `FileWriterAgent` and the office writers, and `write_file`'s failure line outside the strict context, format the caller's path; in `edit_file` a `FileNotFoundError` from the runtime's `config_path` or a logging filter is reported as a missing file.
- *Reversal.* Revert the BF-911 commits. Nothing persisted changes.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

The orchestrator appends the *Mutation campaign of record* bullet to this entry after the campaign runs, as BF-910 and AD-1344 S1 did.

### Ledger

After both edits: `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (write mode), which regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`. Both belong to the M3 commit. Then `--check`.

### Not updated

`docs/development/roadmap.md` (D13). `config/`, `.github/`, `scripts/`: untouched.

### GitHub (orchestrator)

- #1613: delivered; closes on merge.
- #1523: the residuals R1–R9 below, each given its F-number.
- `docs/research/reference-projects.md` row updates under Prior Art (next docs change).

---

## Deterministic gate checks (resolved up front)

| Check | Result |
|---|---|
| AD-1344 S1 after its Amendment A1 (`d2447e09`) | S1's T38 (`test_ad1344…:626-642`) counts the caller's `__str__` calls through both SWE tools; BF-911's call judges `path_text`, so the count stays 1 (D15). S1's T37 (`:590-611`) drives the constitution, which AD-1344's call refuses ahead of BF-911's, so its log assertions see S1's line. S1's census A (`:856`) counts `constitution_write_refusal` calls and census B (`:873`) write primitives in its scope; BF-911 adds neither. |
| srp-size (class span > 500 or > 15 direct methods, `check_architecture_principles.py:187-188`, classes only) | No method added to any class. Growth: `WriteFileTool` (`tools.py:970-1051`, 82 lines) +4; `EditFileTool` (`:1054-1172`, 119) +4; `FileWriterAgent` (`file_writer.py:16-157`, 142) +13; `DocxAgent` (`skill_framework.py:72-278`, 207) +8; `PptxAgent` (`:279-452`, 174) +4; `XlsxAgent` (`:453-546`, 94) +4. `ProbOSRuntime` (baselined, `architecture-baseline.yaml:871`): one line changed in place. `file_access.py` (847 lines) gains functions, no class. |
| layer-import | Ranked packages are `substrate`, `mesh`, `consensus`, `cognitive`, `experience` (`architecture-baseline.yaml:12-17`). `security` is unranked, so `agents → security`, `skill_framework → security` and `cognitive → security` (already present, `tools.py:54`) add no row. `security` imports nothing from `cognitive` (D10). |
| db-connect / unowned-task | None added. |
| config reference / profiles / facade | No config field; `config.py` and `config/system.yaml` untouched; `check_config_facade.py` scans `config.py` only. |
| store registry | No store or table. |
| seam contracts | `docs/development/seams/` and `tests/fixtures/ad1343_seam_*.py` name none of the touched modules or `commit_write` (Absence Verified). |
| AD ledger | `PROGRESS.md` and `DECISIONS.md` change: regenerate (Section 8). |
| AD-1195 event freeze | No `EventType`. |
| AD-1179 schema golden and vocabulary guards | No schema or `params.get` key added. |
| Import cycle | `file_access.py` gains `posixpath` and `re` only (stdlib); its `probos` imports stay function-level (`:182`, `:235`, `:251`). M1 and M2 run a fresh-interpreter import. |
| Hidden pins | `test_builder_guardrails.py:36` and BF-894 `_LEGIT` (`:31`): builder untouched. BF-908 floor tests: `protected_config_files` unchanged; `_REPO_DEFAULT_CONFIG == _repo_default_config_path()` (`test_bf908_floor_and_children.py:299`) unchanged. AD-1344 S1's tests: unchanged file; its writers keep their calls; census A (callers of AD-1344's rule) and B (write primitives) see no new site. `test_utility_agents.py:837-840` patches `commit_write` with `return_value=`: the patched mock accepts `runtime=`. `test_ad1284…:412-429` (`path=123` stays noisy): `Path(123)` raises inside `commit_write`'s `try` before either rule. `_GateRuntime` (`test_ad1284…:114-127`) overrides `submit_write_with_consensus`, so it never reaches `commit_write`. |

---

## Caller-code operations against the base (BF-910 lesson)

Base = `d2447e09` (S1 final). "Caller code" = a method of a value the caller chose.

| Writer | On the base | Added by BF-911 | Where |
|---|---|---|---|
| `WriteFileTool.invoke` | outside the `try`: `refuse_undeclared_params`, `not path`, `content is None`; inside: `str(path)` once (`:1013`, S1's `path_text`), `str(content)` twice on each branch (`:1033` or `:1037`, and `:1039`); the handler's `logger.warning` formats `path` and `exc` (`:1050`) | none: the call judges `path_text` (D15) | inside the existing `try`, between S1's refusal and `_resolve_path` |
| `EditFileTool.invoke` | outside: `not path`, `old is None or new is None`, `bool(params.get("replace_all", False))`; inside: `str(path)` once (`:1102`, S1's `path_text`), `str(old)`, `str(new)`; handlers format `path` (`:1168`) and `exc` (`:1172`) | none: the call judges `path_text` (D15) | inside the existing `try`, between S1's refusal and `_resolve_path` |
| `FileWriterAgent.act` | inside the `try`: `Path(path)`; `str(p)` of a `Path`; the handler formats `str(e)` | `str(p)` of a `Path` (no caller code) | inside |
| `FileWriterAgent.commit_write` | the same | `str(p)` of a `Path` | inside |
| office `create_docx`, `create_pptx` | no `try`: `os.path.expanduser(output_path)`, `Path(...)`, `str(target)` | `str(target)` of a `Path` | no `try`, as on the base |
| office `revise_docx`, `update_xlsx` | no `try`: `Path(file_path)`, `.suffix`, `.exists()`, `str(source)` | `str(source)` of a `Path` | no `try`, as on the base |
| `submit_write_with_consensus`, `_mesh_write_file` | — | passes the runtime object | — |

The rule reads an exact `str` and nothing of another value; `protected_config_files` reads `runtime.config_path` (the writer's own runtime, not a caller value); the rule formats an exception class name through `_exception_class_name` (D17). No handler changes. An exception the rule lets propagate (one that is not among the `OSError`/`ValueError`/`RuntimeError` cases it turns into refusals) enters the handlers of the `try` holding the call, in their order (D16): `write_file` and both `FileWriterAgent` functions have one `except Exception`; `edit_file` has `except FileNotFoundError` (`tools.py:1161`), then `except Exception` (`:1169`); the office writers have no `try`. T39 pins the `except Exception` route for both SWE tools. In the rule, `Path.resolve` and both `os.stat` calls catch `FileNotFoundError`; from Section 1c's statements, one can come from the runtime's `config_path` attribute or its `__str__` (`file_access.py:213`, `:220`) or from a logging filter, and `edit_file` reports it as a missing file (R11).

**Filesystem access before the write.** The rule resolves the target (`Path.resolve`, which also `stat`s it) and `os.stat`s it, and `os.stat`s each protected file. AD-1344's check, which runs first, already resolves the same target and `stat`s it whenever a constitution file exists, and the base writer opens the path; so no new path form (a UNC path included) is contacted that the base did not touch. The new accesses are the `os.stat` of the protected files: the operator's own `--config`, the checkout default and `~/.probos/config.yaml`, which the read floor already resolves on each guarded read.

---

## Diff Reviewer: properties to verify

1. In each function of `_EXPECTED_CALLERS`, the BF-911 call comes after the AD-1344 call and before every operation that creates, opens for writing, truncates, saves or links a file at that path (`mkdir`, `write_text`, `save`, the strict-native open).
2. Each refusal string contains `BF-911` and no line break. It formats exact `str` values: the path through `repr`, and an exception class name that is an identifier, else the literal `Exception` (D17, T36). The non-`str` reason formats nothing.
3. `protected_write_refusal` returns non-None in exactly the cases its docstring lists; every other exception propagates.
4. `_exception_class_name` reads no attribute of an exception class whose metaclass is not exactly `type`, and returns a class name when it is an exact-`str` identifier, else `Exception` (D17); its body equals `builder_paths._exception_name`'s.
5. The protected set is `protected_config_files(runtime)` plus `PROTECTED_LEAF_NAMES`; no second list of config paths exists.
6. `commit_write`'s `runtime` is keyword-only with default `None`; every call passes `runtime=`; the consensus commit passes the runtime object.
7. For a path that is not a protected file, a vault name or an identity alias, each writer behaves as on the base tree; the AD-1344, BF-908, BF-758 and consumer suites pass unchanged.
8. Caller-code operations match the table above: nothing new outside a `try` that held it on the base, no handler changed.
9. No change to `builder_paths.py`, `builder.py`, `copilot_adapter.py`, `routers/`, `scripts/`, `.github/`, `config/` or `config.py`; no chmod or lock.
10. The mirrored helpers equal BF-894's (T19); `security/file_access.py` imports nothing from `probos.cognitive`.
11. Writer-level tests write only under `tmp_path`; the home directory is redirected in `layout` before any writer runs; the autouse guard only reads files.
12. No import cycle; no new layer-import, srp-size, db-connect or unowned-task row.
13. Tracker and docstring prose makes no claim about when a state holds, and each universal word is pinned by a named test or enumeration.
14. Each of the eight BF-911 `logger.warning` calls has one argument, a string literal `BF-911 <Writer> refused operation=<op> reason_code=protected_write_refused` (D16, T37, T40). In the SWE tools the call passes `path_text` (D15, T38).

---

## What This Does NOT Change

- The builder boundary, the test-fix loop, the visiting session's permission handler, `FIX_LOOP_PROTECTED_PATHS`.
- BF-908's read floor and `protected_config_files`.
- The Captain's channels: the HXI settings route (`routers/config.py:262`), `probos setup`/`init`, an editor, git, hooks, CI.
- Shell (`run_command`), `run_python`, `install_package`, MCP servers, agent-designed code.
- The effect broker and its adapters.
- Other `config/` files (standing orders, profiles), the data directory and its stores.
- The credential model (option D).

## Interplay

- **AD-1344 S1** (final at `d2447e09`; this builds after it merges): BF-911 adds a call after each of S1's writer calls, judges S1's `path_text` in the SWE tools, and imports S1's test helpers. S1's test file is not edited; S1's 24 rows on `tools.py`, `file_writer.py` and `skill_framework.py` are rerun on BF-911's tree (Mutation table).
- **AD-1343** (merged): no stop check inside these writers; no registry entry (D14).
- Nothing else in flight is coordinated.

## Residuals (for #1523; the orchestrator numbers them)

- **R1** Shell and code execution (`run_command`, `run_python`, `install_package`) can still write a config file.
- **R2** MCP servers and agent-designed code are not path-gated.
- **R3** Check and write are separate steps; a link swapped in between is caught only on the Windows strict-native handle path (`tools.py:186-217`).
- **R4** The data directory is not on the write floor; the vault is refused by name, so a hard link to it under another name is not.
- **R5** A writer without a runtime knows only the two defaults: the `FileWriterAgent` proposal (its pool is created without one, `startup/agent_fleet.py:57`) and a direct `commit_write` without `runtime=`. The commit after consensus passes it.
- **R6** A relative `--config` resolves against the working directory at check time (`protected_config_files`).
- **R7** A link to the live config placed inside a build worktree: the builder does not call the rule (D6).
- **R8** Over-refusal: 8.3-shaped names sharing the first two characters, and case variants on case-sensitive filesystems.
- **R9** The census reads AST call names: dynamic dispatch and names imported under another alias are outside it.
- **R10** AD-1344's refusal log lines in `FileWriterAgent` (`file_writer.py:113`, `:147`) and the office writers (`skill_framework.py:211`, `:263`, `:410`, `:535`) format S1's reason, which holds the caller's path; `write_file`'s failure line outside the strict context formats `path` (`tools.py:1050`). BF-911's own lines format nothing (D16); S1's lines are S1's contract.
- **R11** In `edit_file`, a `FileNotFoundError` raised inside the `try` by the runtime's `config_path` attribute or its `__str__`, or by a logging filter, takes `except FileNotFoundError` (`tools.py:1161`): it is reported as a missing file, or as `NoEffectFailure("file_not_found")` under the dispatch context. Nothing is written.

## Acceptance Criteria

1. Each writer in `_EXPECTED_CALLERS` refuses the live config in each form its test drives, the loaded `--config` file through its runtime, and the absent `~/.probos/config.yaml`, with a reason naming BF-911 (T20–T30). A hard link is refused through each writer whose test makes one; a directory link through the rule and `write_file`.
2. The neighbours, a worktree copy and a build's worktree config stay writable (T3, T6, T21, T25, T26, T28–T31).
3. The census tests pass (T32–T35).
4. The campaign of record kills every row of the mutation table (66 rows with Amendment A1), and S1's 24 rows on `tools.py`, `file_writer.py` and `skill_framework.py` stay killed on this tree.
5. One receipted broad gate and CI are green.
6. No friction: T18 and T35 pass, and the diff touches no hook, CI or `config/` file.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Prior Art and Blind Spots

Date used for the overdue check: **2026-10-21**.

| Source | Decision |
|---|---|
| BF-758/BF-908 read floor (`security/file_access.py:98-228`) | **Reuse** `protected_config_files` and `PROTECTED_LEAF_NAMES` as the one list. |
| AD-1344 S1 (`builder_paths.py:66-196`; its Amendment A1 D20–D22) | **Adapt**: the canonical form, the exact-`str` gate, the identity loop, metaclass-safe and identifier-only naming, the constant log line and the one conversion; whole-path matching instead of a tail, so copies stay writable. |
| OpenAI Codex sandbox: `workspace-write` keeps `.git`, `.codex` and `.agents` read-only inside writable roots, and protects the directory a `gitdir:` pointer resolves to ([docs](https://developers.openai.com/codex/concepts/sandboxing)) | **Absorb** the principle: protect the agent's own configuration inside its writable area, and judge the resolved target, not the spelling. |
| Claude Code: `.claude/settings.json` is a protected path, and community tests show deny rules on Edit do not stop shell writes ([Classmethod](https://dev.classmethod.jp/en/articles/claude-code-protect-settings-json-deny-rule-protected-paths/), [settings docs](https://docs.anthropic.com/en/docs/claude-code/settings)) | **Absorb**: refuse at the tool level and keep the shell as a named residual (R1). |
| CVE-2026-35603 (a config file dropped into a folder AI coding tools trust; [Cymulate](https://cymulate.com/?p=33306)) | **Absorb**: an absent config file that would be loaded is refused by name (D2). |
| SWE-agent, Cursor (overdue; examined by AD-1344 S1 on 2026-10-21, its row updates pending) | Not repeated. |
| OpenCode (overdue since 2026-05-08) | Considered, deferred: not relevant to write boundaries. |

**Reference-projects row updates** (for the orchestrator's next docs change):
- OpenAI Codex → `2026-10-21 | checked | BF-911 (#1613) Prior Art, prompts/bf-911-protected-config-write-refusal.md (workspace-write protected paths .git/.codex/.agents; gitdir pointer target protected)`
- Claude Code → `2026-10-21 | checked | BF-911 (#1613) Prior Art (protected settings path; Edit deny rules do not cover shell writes, from community reports)`

**Blind spots:**
1. Creating an absent `~/.probos/config.yaml` (D2), reachable from the bundled notes agent; T2 and T28 pin it.
2. A copy with identical content in another tree is a different file and stays writable (T6); refusing by content would break builds.
3. TOCTOU (R3) and the runtime-less proposal (R5).
4. Writes that only delete or rename a config file: AD-1344's census B classifies every `unlink`, `rmdir`, `rename`, `replace` and `rmtree` site in the agent-facing modules with a fixed path, so none takes a caller-chosen path.
5. The read floor's `protected_config_files` docstring still says it does not cover a hard link; that remains true for reads.

---

## Verified Against Codebase (2026-10-21, on `f3747799` = `7171aded` + AD-1344 S1 candidate)

```
git log --oneline -3 -> f3747799 scratch: AD-1344 S1 frozen candidate r1; 957b249e AD-1344 S1 contract; 7171aded Merge PR #1612
security/file_access.py:36-48 imports (logging, ntpath, os, stat at :38-41; no re/posixpath); :31-34 docstring tail; :59 _REPO_DEFAULT_CONFIG; :66-69 PROTECTED_LEAF_NAMES
security/file_access.py:190-199 protected_read_roots; :202-228 protected_config_files (getattr config_path, _REPO_DEFAULT_CONFIG, Path.home()/.probos/config.yaml; resolved; isinstance str/Path); :231 _protected_data_dir; :336 splitdrive(spelling)
security/__init__.py: 1 line, no imports
swe_harness/tools.py:23 S1 import; :54-61 file_access import (protected_read_roots :57); :73 logger; :76 _PROJECT_ROOT = parents[3]; :242-245 _resolve_path
swe_harness/tools.py:970 WriteFileTool; :990-991 self._runtime; :1012-1017 try, S1 call, S1 logger/return, _resolve_path; :1040-1050 handler
swe_harness/tools.py:1053 EditFileTool; :1075-1076 self._runtime; :1100-1105 try, S1 call, _resolve_path; :1159-1170 handlers; :1353-1392 register_native_swe_tools (runtime passed to each tool); :1372-1377 write perms
agents/file_writer.py:7 Any; :9-11 imports; :13 logger; :105-115 act try, S1 call; :140-157 commit_write (@staticmethod, S1 call :145)
substrate/agent.py:55 self._runtime = kwargs.get("runtime"); substrate/skill_agent.py:28-29 **kwargs to BaseAgent
startup/agent_fleet.py:48,57 file_writer pool created without runtime; :312-327 office pools with runtime=runtime
runtime.py:1285 self.config_path; :4753 submit_write_with_consensus (no decorator); :4781-4783 commit_write(path, content); :4785-4789 event_log.log; :5243-5256 _gated_commit_write
__main__.py:78-80 _probos_home; :486-489 _repo_default_config_path; :492-503 _resolve_config_path (home config preferred when it exists); :639 runtime.config_path
agents/utility/organizer_agents.py:56-66 _mesh_write_file (:65 commit_write); :119 _NOTES_DIR; :187-191 model-chosen filename
agents/utility/productivity_agents.py:116-126 _mesh_write_file (:125); :162 _TODO_PATH
skill_framework.py:21-23 imports; :27 logger; :72 DocxAgent; :207-215 create_docx; :252-269 revise_docx; :279 PptxAgent; :406-414 create_pptx; :453 XlsxAgent; :524-545 update_xlsx
cognitive/builder_paths.py:49-55 ALLOWED_PATH_PREFIXES ("config/" :52); :66 _HFS_IGNORABLE; :68 _SHORT_NAME; :74-76 _canonical; :87-89 _exception_name; :142 constitution_write_refusal; :240; :440-477 operator_checkout_refusal
cognitive/builder.py:48 _PROJECT_ROOT = checkout; :3158-3164 operator_checkout_refusal before any git command
routers/build.py:29 _REPO_ROOT = parents[3]; :118; routers/config.py:262 config_path (HXI settings write)
cognitive/copilot_adapter.py:110 protected_read_roots; :269-293 _session_relative; :322 builder_write_refusal(rel)
credential_store.py:428 crew_scope_token; security/crew_scope.py:99-107 configured_crew_scope_token
config.py:3736 OfficeSkillsConfig.enabled False; :3819 effect_broker_enabled False
tests/test_ad1344_constitution_write_refusal.py:111 _dir_link; :406-413 _no_real_git; :420-425 _build; :697 _CHANNEL_SUFFIXES; :700 _tracked; :709 _calls; :729 _callee; :761 _source
tests/test_bf894_builder_write_boundary.py:31 _LEGIT; tests/test_builder_guardrails.py:36; tests/test_bf908_floor_and_children.py:224-228 (Path.home patched), :299
tests/test_utility_agents.py:837-840; tests/test_ad1284_consensus_gate_reachability.py:33-41 imports (ConsensusOutcome from probos.types), :114-127, :412-429
docs/development/architecture-baseline.yaml:12-17 layers; :871 ProbOSRuntime; check_architecture_principles.py:80-85, :187-188, :558-569 (srp-size counts classes)
PROGRESS.md:1 "# ProbOS Progress", :3 AD-1344 S1 entry; DECISIONS.md:422 BF-910, :436 AD-1346 M3a, :455 AD-1344 S1, :467 "### Explicit delegation models ..." (one occurrence)
pyproject.toml:181-196 (asyncio_mode auto; addopts -n 16; no ruff/isort); .github/workflows/ci.yml:71 pytest only
scripts/ad_ceiling.py -> CEILING AD-1346, NEXT AD-1347
```

## Re-verified on `d2447e09` (Amendment A1, 2026-10-21)

| Claim | Evidence (read on `d2447e09`) |
|---|---|
| HEAD | `git log --oneline -4`: `d2447e09` (S1 campaign of record), `b6c71a87` (S1), `9a9cfe01` (S1 contract A1), `957b249e` |
| SWE tools | `tools.py:970` WriteFileTool; `:1013` `path_text = str(path)`; `:1014` S1 call; `:1016` S1 constant line; `:1018` `_resolve_path(path_text)`; `:1039` output `path_text`; `:1041` `except Exception`; `:1050` `AD-544 … path=%s`; `:1054` EditFileTool; `:1102`, `:1103`, `:1105`, `:1107`; `:1160`; `:1161` `except FileNotFoundError`; `:1168`; `:1169` `except Exception`; `:1172`; `:73` logger; `:1355`, `:1396-1397` |
| FileWriterAgent | `file_writer.py:9-10` imports; `:13` `logging.getLogger(__name__)`; `:111-115`; `:131` `except Exception`; `:140-149`; `:156` `except Exception` |
| Office | `skill_framework.py:27` logger; `:192`, `:207-215`; `:252`, `:256-264`; `:373`, `:408-411`; `:524`, `:528-536`; `try` in `:72-612` at `:177` (`summarize_docx`), `:236` (`_synthesize_paragraphs`), `:436` (`_synthesize_slides`) |
| Floor | `file_access.py:202-228` (`:213` getattr `config_path`, `:216`, `:220` `str(candidate)`, `:224`) |
| S1 helper | `builder_paths.py:87-96` `_exception_name` (`:92` `cls = type(exc)`, `:96` identifier return); `:447-484` `operator_checkout_refusal` |
| Callers | `runtime.py:4782`, `organizer_agents.py:65`, `productivity_agents.py:125` (positional `commit_write`); `tools/executor.py:866`, `:870` |
| S1 tests | 39 test functions (`:177` to `:897`); `:111`, `:442`, `:456`, `:590-611` T37, `:614` `_ShiftingPath`, `:626-642` T38, `:730`, `:758`, `:788`, `:791`, `:800`, `:820`, `:852`, `:856` T34, `:873` T35, `:897` T36 |
| Trackers | `DECISIONS.md:455`, `:463`, `:466`, `:469` (heading, one occurrence); `PROGRESS.md:1`, `:3` |
| Absent: A1's new `file_access.py` lines | Grep `cls = type\(exc\)\|if type\(cls\) is not type:\|name = cls\.__name__\|return name if type\(name\) is str and name\.isidentifier\(\) else "Exception"` in `file_access.py`: none |
| S1's other writers log the reason (R10) | Grep `AD-1344` in `file_writer.py`: `:113`, `:147`; in `skill_framework.py`: `:211`, `:263`, `:410`, `:535`; each `"…: %s", refused` |

## Absence Verified (2026-10-21)

| Claim | Run | Found | Holds |
|---|---|---|---|
| No writer consults the config floor | Grep `protected_config_files\|protected_read_roots\(\|protected_write_refusal` in `src/probos` | `code_search.py:337`, `copilot_adapter.py:110`, `repository_instructions.py:62`, `file_access.py:190-265`, `tools.py:335,909`: all reads; `protected_write_refusal`: none | yes |
| The new names are free in `file_access.py` | Grep `_write_key\|_same_key\|_canonical_name\|_HFS_IGNORABLE\|_SHORT_NAME\|_DEVICE_PREFIXES\|_NOT_A_STR\|_CONFIG_FILE\|_VAULT_FILE\|_exception_class_name\|_protected_refusal\|_protected_unverifiable\|_PROTECTED_LEAF_KEYS\|^import re\|^import posixpath` | none | yes |
| `commit_write` has three callers | Grep `commit_write\(` in `src/probos` | `runtime.py:4782`, `organizer_agents.py:65`, `productivity_agents.py:125`; plus the definition `file_writer.py:141` and docstrings (`file_writer.py:46,97`, `productivity_agents.py:120`, `organizer_agents.py:60`, `execution/isolation.py:20`) | yes |
| No other agent-reachable writer takes a caller-chosen path that can name a config file | Grep `\.write_text\(\|\.write_bytes\(\|os\.replace\(\|shutil\.(copy\|copy2\|copyfile\|move)\(\|open\(...["'](w\|a\|x\|r\+…)` in `src/probos`: 106 hits in 55 files; triaged the ones outside AD-1344's census scope that could take a model or intent value | `evidence_collector.py:559` (`{obs_id}.yaml` under its output dir), `self_improvement/versioning.py:145,157` (`{agent_type}_v{N}.py`/`.meta.yaml`), `records_store.py` (`_safe_path` containment, `:1202-1213`), `knowledge/store.py` (its repository), `dm/artifact_extractor.py:198` (a temp dir), `execution/isolation.py:1013,1027` (fixed names in a workdir), `runtime_config_service.py:104` (its own overrides file), `routers/config.py`, `provider_setup.py`, `__main__.py` (the Captain's channels); AD-1344's census B classifies the rest | yes |
| No test asserts `commit_write`'s exact arguments | Grep `commit_write` in `tests/` | `test_utility_agents.py:837-840` (`patch(..., return_value=...)`), AD-1284's `_GateRuntime` overrides the caller, S1's and `test_file_writer.py` call it positionally | yes |
| No test writes a runtime's `config_path` through these writers | Grep `config_path\s*=` in `tests/` (31 files), triaged | config API, doctor, `load_config` fixtures and BF-908/BF-910 read tests write directly, not through a guarded writer | yes |
| No seam manifest or registry names these modules | Grep `file_access\|organizer_agents\|productivity_agents\|submit_write_with_consensus\|file_writer\|skill_framework\|swe_harness` in `docs/development/seams/`; `commit_write\|write_file\|submit_write\|_mesh_write_file\|file_access` in `tests/fixtures/ad1343*.py` | none | yes |
| No roadmap row for recent BFs | Grep `BF-9(0\|1)[0-9]` in `roadmap.md` | 0 | yes |
| No BF-911 artefact exists | Glob `tests/test_bf911*`, `prompts/bf-91*.md`; `git log --all --grep "BF-91[0-9]"` | `prompts/bf-910-…` only; commits name BF-910 only | yes |
| No linter enforces import order | Grep `ruff\|isort\|select\s*=` in `pyproject.toml`; `ruff\|mypy` in `ci.yml` | none; CI runs pytest | yes |

**Not verified here.** No test ran on this tree: the venv's `probos` resolves to `D:\ProbOS\src` (an import of S1's test file failed on `constitution_write_refusal`), and the bridge allows no `PYTHONPATH` prefix. The orchestrator's dry run (with `PYTHONPATH=<tree>\src;<tree>`) is the first execution of the code and tests above. `gh` was not used; the issue text came from `issue-1613-body.md`.

---

## Amendment A1 (2026-10-21, `claude-architect`, re-anchored on `d2447e09`)

Applied in place by the orchestrator: pairs A1-1 to A1-8 took the place of the pairs 2b, 2c, 3b, 3c, 6b, 6c, 6d and 6e (each label line says so); pairs A1-9 to A1-47 edited the text of this file. The pairs above are therefore the whole set the Builder applies, once each, in order. The Architect's answer (the decisions below, then the 47 pairs) is banked outside the repository.

Decisions:
- **Placement:** in both SWE tools, BF-911's call goes between S1's refusal block and `target = _resolve_path(path_text)`, and it judges `path_text`.
- **Order:** AD-1344's call first, then BF-911's (D5 is kept).
- **Log line:** each of BF-911's eight log lines is a constant, `BF-911 <Writer> refused operation=<op> reason_code=protected_write_refused`, with no caller value.
- **Exception name:** `_exception_class_name` copies the body of S1's D22 helper.

**Why `path_text` is required, not just preferred.** S1's T38 (`tests/test_ad1344_constitution_write_refusal.py:626-642`) drives both tools with `WriteFileTool(SimpleNamespace())` and asserts `conversions == 1` (`:632`, `:639`). The drafted `protected_write_refusal(str(path), …)` would call the caller's `__str__` a second time, so S1's own test would fail on BF-911's tree.


---

## Orchestrator pre-build verification (2026-10-21, on `3dfb6f81`)

Run on scratch worktrees before any Builder, as for AD-1344 S1 and AD-1346 M3a. The evidence files are outside the repository. AD-1344 S1 merged as `3dfb6f81` (PR #1614, "Part of #1596"); its tree `5e72cb12c1451e723e1a1822f2f73b6bf92bcb36` is the gated tree and the tree of `d2447e09`, on which the scratch trees below were built.

| Check | Result |
|---|---|
| Every SEARCH against `3dfb6f81` (`check_search_replace_blocks.py` on this amended file) | 19 pairs (Amendment A1 replaced eight of them in place, so the count did not change; its prose says 18); each SEARCH occurs exactly once |
| The whole amended contract applied (19 pairs and the new file), AD ledger regenerated | applied; `gen_ad_ledger.py --check` reports current |
| `tests/test_bf911_protected_config_write_refusal.py`, `-n 4` | 114 passed (40 test functions), no skip (this host can make hard links and junctions) |
| Focused check: 218 test files (the new file, AD-1344 S1's file, the BF-894 table and every test file that names a changed surface), scrubbed environment, `-n 8` | 12,252 passed, 51 skipped, 3 failed. The three are the AD-ledger tests (`test_ad1184_ad_ledger.py`) before the contract's M3 ledger step had run on the scratch tree; after `gen_ad_ledger.py`, `test_ad1184_ad_ledger.py` and `test_ad1343_seam_registry.py` pass (41 passed). The skips are symlink privilege (24), POSIX-only (23), the uninstalled `github-copilot-sdk` (3) and one Windows-only rename (1); none is in the new file, AD-1344 S1's file or the BF-894 table |
| The new file, AD-1344 S1's file and the BF-894 table, unscrubbed, `-n 0` | 327 passed |
| `check_architecture_principles.py --check` (srp-size 92, layer-import 0), `check_seam_contracts.py`, `check_store_registry.py --check`, a fresh-interpreter import of the seven changed modules | pass |
| The mutation table, 66 rows | 66 killed by a named test (27, 31 and 8 rows in three worktrees); none INVALID |
| AD-1344 S1's 24 `W` rows on this tree, against S1's unchanged test file and the BF-894 table | 24 killed |
| The two mutants the contract calls equivalent | both survive (261 passed), as the contract argues |
| Platform | every check above ran on Windows, Python 3.12.13; CI runs `ubuntu-latest`, Python 3.12, and is the first Linux run. The OS-dependent code in the new file is its link helpers (a junction on Windows, a symlink elsewhere, and hard links); the tests that need a link skip when the host cannot make one |

**Corrections applied before the build:** none to the contract's code or tests. The one count in Amendment A1's prose (18 tree pairs) is 19.

**Tools the orchestrator used** (outside the repository): `bf911_amend_contract.py` built this file from the drafted contract and the Architect's answer (47 pairs: 39 text edits and 8 in-place replacements); `bf911_campaign_table.py` turned the mutation table into the runner's rows (66, the two equivalents and S1's 24).
