# AD-1344 S1: agents cannot amend the Federation Constitution (#1596, Slice 1 only)

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-19 (first draft, on `45058ae7`); redrafted 2026-10-21 on `e237c352`
**Status:** build-ready contract. **Tier: HIGH** (a write boundary on agent-authored change).
**Number:** AD-1344 is allocated (the issue). Ceiling run 2026-10-21, `scripts/ad_ceiling.py`: CEILING AD-1346 (git subjects, issue titles, prompt filenames), NEXT AD-1347. Nothing allocated here.
**Base:** `origin/main` `7171aded` (BF-910, AD-1346 M1a and AD-1346 M3a merged; the draft was written on `e237c352`). The orchestrator re-ran every SEARCH pair against `7171aded` and each occurs exactly once; see "Orchestrator pre-build verification and corrections" at the end.
**Scope:** Slice 1 of #1596. Slice 2 (a formal amendment process) stays under the new-capability pause and is not built or outlined here. **#1596 stays OPEN.**
**Estimated tests:** 36 test functions (about 140 collected items) in one new file, plus 2 rows added to an existing table (`tests/test_bf894_builder_write_boundary.py`).

---

## Problem

- The builder boundary allows `config/` (`src/probos/cognitive/builder_paths.py:41-47`) and forbids only `.git/`, `.env`, `pyproject.toml` and `.github/` (`:50-55`). The native build (`builder.py:3252`) can therefore write `config/standing_orders/federation.md`, and so can the visiting session's permission handler (`copilot_adapter.py:322`). The fix loop (`builder.py:3496`) is refused there only by BF-898's "outside src/probos" rule (`builder_paths.py:207`).
- SWE-harness `write_file` (`swe_harness/tools.py:969`) and `edit_file` (`:1048`) join a relative path to the project root, or take an absolute path as given (`_resolve_path`, `:241-244`). Neither applies a deny rule.
- `FileWriterAgent.commit_write` (`agents/file_writer.py:136-148`) writes the path it is given. It is reached after consensus (`runtime.py:4767`) and directly from the bundled todo, notes and reminder agents (`productivity_agents.py:125`, `organizer_agents.py:65`). The notes filename comes from the model's output (`organizer_agents.py:187-191`).
- The office writers `create_docx` and `create_pptx` save to the `output_path` an intent supplies (`skill_framework.py:206-210`, `:397-401`). `revise_docx` and `update_xlsx` save over an existing `.docx` or `.xlsx` (`:251-260`, `:515-528`), and that includes a hard link to the constitution.

## Solution

`standing_orders.py` publishes where the constitution is: `CONSTITUTION_FILENAME`, `CONSTITUTION_RELATIVE_PATH` and `constitution_path()`, next to BF-910's `standing_orders_dir()`.

`builder_paths.constitution_write_refusal(path, root=None)` returns a one-line reason naming AD-1344 for:

1. a value that is not an exact `str`. Nothing of the value is read or formatted;
2. a path whose last three components, as written, name `config/standing_orders/federation.md`. Before comparing: separators become `/`, a leading drive (`C:`) is dropped, `..` is collapsed, each component loses any `:` suffix (an NTFS stream) and is put in BF-894's canonical form, and components that are then empty are dropped. A component in 8.3 short form with the same first two characters also matches. This applies in any tree;
3. the same test on the resolved path;
4. an existing file with the same `os.stat` identity as the constitution under `root`, or as `constitution_path()`;
5. an examination that raises `OSError` or `ValueError` (other than not-found), or a resolution that raises `OSError`, `RuntimeError` or `ValueError`.

Any other exception propagates to the writer. Each writer's sequence calls the rule before its own write.

`builder_write_refusal` runs cases 1 and 2 right after its empty-path check, so the AD-1344 reason is the one given. With a `work_dir`, it runs the whole rule after the `.git` identity check. The SWE tools, `FileWriterAgent` (proposal and write) and the four office writers call the rule directly. This contract touches no hook, CI file, file mode or Captain's channel.

---

## Decisions

D1 to D13 are the 2026-10-19 decisions re-verified on `e237c352`. D14 onward are new.

| # | Decision | Status on `e237c352` | Rejected alternatives |
|---|---|---|---|
| D1 | The rule lives in `cognitive/builder_paths.py` as `constitution_write_refusal(path, root=None) -> str \| None`. | **Holds.** The file is unchanged since `45058ae7`. It is still in `FIX_LOOP_PROTECTED_PATHS` (`:147`) and has no class. | A new `security/constitution.py`: it would need a new protected path plus a self-test row (BF-898 pin `test_bf898…:150-157`) for no gain. `security/file_access.py`: read-side and runtime-coupled. |
| D2 | `standing_orders.py` owns the location (`CONSTITUTION_FILENAME`, `CONSTITUTION_RELATIVE_PATH`, `constitution_path()`). The literals at `:175` and `:476` use it. | **Changed anchor.** BF-910 added `standing_orders_dir()` (`:103-105`), so `constitution_path()` returns `standing_orders_dir() / CONSTITUTION_FILENAME` and sits right after it. | Defining the path in `builder_paths.py`: the composer would then import a write boundary. |
| D3 | The refused set is cases 2 to 5 above. Copies in other trees are refused on purpose. | **Changed.** (a) My draft had a bypass. A drive-relative path (`C:config/standing_orders/federation.md`) lost its first component to the stream-suffix strip, and the "relative with no root" early return then accepted it. The leading drive is now dropped before comparing, and the rule always resolves (no early return). (b) Case 1 is new (D14). | A lexical rule only: misses hard links (CVE-2025-59829 class). An OS handle lock: Windows-only, and friction for the Captain's editor. |
| D4 | In `builder_write_refusal` the lexical check runs first and the identity check runs last, after `_git_identity_refusal`. | **Holds.** The NUL premise `test_bf898…:250-255` still needs `.git` first. The BF-894 fail-closed test (`:122-136`) and hard-link test (`:105-113`) also keep `.git`'s reasons first. | Running the constitution identity check first: it would change those reasons. |
| D5 | The office writers (`docx_create`, `docx_revise`, `pptx_create`, `xlsx_update`) are guarded too. The issue's list omits them. | **Holds.** Anchors unchanged (`skill_framework.py:206-210`, `:251-260`, `:397-401`, `:515-528`). The writers are spawned only with `office_skills.enabled` (default `False`, `config.py:3736`). | Leaving them out: acceptance 1 says "every agent-reachable writer". |
| D6 | No code change in the Copilot adapter. | **Holds; anchor moved** `:254` → `:322`. `rel` is an exact `str` (`os.path.relpath(...).replace`, `:291`). Approved blocks return through `execute_approved_build` with `work_dir`. | — |
| D7 | The SWE tools, `FileWriterAgent` and the office writers call the rule directly, not through `builder_write_refusal`. | **Holds.** `builder_write_refusal` also applies builder-only rules: the allowed prefixes (`:41-47`) and the absolute-path refusal (`:83`). | Calling `builder_write_refusal`: it would change their behaviour on other paths. |
| D8 | Two AST censuses in the new test file pin the inventory. `architecture-baseline.yaml` is untouched. | **Changed.** The census scope gains `cognitive/skill_forge.py` and `cognitive/skill_catalog.py`, which agents reach through generated skills. The channels scan reads only executable files (`.py .ps1 .sh .yml .yaml .toml .cfg`), so docs that name the rule do not fail it. | A census of intent and tool names: every later intent would have to edit it. |
| D9 | Each writer refuses in its own error shape: the SWE tools return `ToolResult(error=...)`, `FileWriterAgent` returns `{"success": False, "error": ...}`, and the office writers raise `PermissionError`. | **Changed placement.** In the SWE tools, the call is the first statement of the `try` that already held `str(path)` on the base (BF-910 F1/F3). | A check before the `try`: it would move `str(path)` outside the `try`. |
| D10 | No addition to `FIX_LOOP_PROTECTED_PATHS`. | **Holds.** The fix loop cannot write `tests/`, so tests the fix loop can't edit pin the writer call sites (census A) and the literal location (T1 asserts the string `config/standing_orders/federation.md`). | Protecting `standing_orders.py`: it would block legitimate repairs to the composer. |
| D11 | `FIX_LOOP_SELF_TEST` gets no rows. BF-894's `_LEGIT` gains two neighbour rows. The refused forms live in the new file's table, judged through `builder_write_refusal` and `fix_loop_write_refusal` too. | **Holds.** | A constitution row in the self-test: it passes without AD-1344 (BF-898 refuses anything outside `src/probos`), so it proves nothing. |
| D12 | No roadmap row. | **Holds.** Searched `AD-134[0-9]` in `roadmap.md`: 0 matches. | — |
| D13 | No config field. `config/system.yaml` untouched. Zero-config boot unchanged. | **Holds.** | — |
| D14 | Case 1: the rule refuses a value that is not an exact `str` before reading anything of it; `builder_write_refusal` returns that refusal from the lexical check after its empty-path check (A1, D23). The reason formats nothing of the value. `_exception_name` reads `type(exc).__name__` only when `type(type(exc)) is type`; otherwise it reports `Exception`. | **New** (the BF-910 caller-code and exception-formatting lessons). Writers pass the result of `str()`: `str(path)` (once, A1 D21), `str(p)`, `str(target)`. A `str` subclass reaching `builder_write_refusal` is refused there; on the base it was judged. | Accepting `os.PathLike`: `__fspath__` would run caller code inside the rule. |
| D15 | Writer-level tests use paths inside a temporary vessel tree only. Forms outside the tree (another drive, another worktree, POSIX absolute, extended-length) go to the rule alone, and a UNC form only to the lexical-only checks (`builder_write_refusal`/`fix_loop_write_refusal` without a `work_dir`). | **New** (mutation safety). A mutant that removes a writer's check then writes only under `tmp_path`, and no UNC host is contacted. | Driving every form through every writer: a surviving mutant would write outside the sandbox. |
| D16 | No seam registration. | **New.** S1 adds no place where agent work starts, no tool invocation and no model call. The AD-1343 registry (`tests/fixtures/ad1343_seam_registry.py`) and the AD-1346 admission package are unaffected. | — |
| D17 | The resolve-failure test injects `ValueError` through `Path.resolve`, so it does not skip. | **New.** My draft's NUL premise could skip on the host, which would leave its mutant unkilled. | — |
| D18 | BF-908 has no write-side sibling, and S1 does not add one. `write_file`, `edit_file` and the builder (`config/` allowed) can still write `config/system.yaml`, which may hold `auth.crew_scope_token`. Recorded as residual R6. | **New.** Out of S1 scope: #1596 acceptance 3 keeps neighbouring `config/` files where they are today. | Widening S1: that would cross the issue's scope. |
| D19 | The effect broker's native-file adapter is unchanged. Under `_effect_dispatch_context`, a refused write returns a `ToolResult` error before either branch (the strict-native lock or the plain write). That is the contract `refuse_undeclared_params` already has (`tools.py:1002`). | **New.** `_NativeFileEffectAdapter.prepare` only resolves (`effect_adapters.py:89-105`). The executor passes `_strict_native_target`/`_strict_native_root` into `invoke` (`executor.py:869-871`). | A denial in `prepare()`: a second copy of the rule. |

---

## Implementation

### Section 0: Event types

None.

### Section 1: `src/probos/cognitive/standing_orders.py`

**1a**

SEARCH:
```python
def standing_orders_dir() -> Path:
    """BF-910: the directory :func:`compose_instructions` reads by default."""
    return _DEFAULT_ORDERS_DIR
```
REPLACE:
```python
def standing_orders_dir() -> Path:
    """BF-910: the directory :func:`compose_instructions` reads by default."""
    return _DEFAULT_ORDERS_DIR


# AD-1344 (#1596): the constitution tier's file and its place under the project root.
# The agent write boundary (builder_paths.constitution_write_refusal) reads both from here.
CONSTITUTION_FILENAME = "federation.md"
CONSTITUTION_RELATIVE_PATH = f"config/standing_orders/{CONSTITUTION_FILENAME}"


def constitution_path() -> Path:
    """AD-1344 (#1596): the Federation Constitution in the directory :func:`standing_orders_dir` returns."""
    return standing_orders_dir() / CONSTITUTION_FILENAME
```

**1b**

SEARCH:
```python
    specs: list[tuple[str, str | None]] = [
        ("federation", "federation.md"),
        ("ship", "ship.md"),
```
REPLACE:
```python
    specs: list[tuple[str, str | None]] = [
        ("federation", CONSTITUTION_FILENAME),
        ("ship", "ship.md"),
```

**1c**

SEARCH:
```python
    # 2. Federation Constitution (universal principles)
    fed = _load_file(d / "federation.md")
    if fed:
```
REPLACE:
```python
    # 2. Federation Constitution (universal principles)
    fed = _load_file(d / CONSTITUTION_FILENAME)
    if fed:
```

### Section 2: `src/probos/cognitive/builder_paths.py`

**2a** (module docstring and imports)

SEARCH:
```python
The identity check applies when ``work_dir`` is given and ``<work_dir>/.git`` exists:
every existing prefix of the target is compared with that entry by ``os.stat``
identity, so any name the filesystem resolves to it (a form the lexical rules do not
name, or a hard link) is refused. A prefix that cannot be examined is refused.
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
```
REPLACE:
```python
The identity check applies when ``work_dir`` is given and ``<work_dir>/.git`` exists:
every existing prefix of the target is compared with that entry by ``os.stat``
identity, so any name the filesystem resolves to it (a form the lexical rules do not
name, or a hard link) is refused. A prefix that cannot be examined is refused.

AD-1344 (#1596): ``constitution_write_refusal`` refuses a write to the Federation
Constitution (``standing_orders.CONSTITUTION_RELATIVE_PATH``); its docstring lists the
cases. ``builder_write_refusal`` calls it, and so do the writers listed in
``tests/test_ad1344_constitution_write_refusal.py`` (``_EXPECTED_CALLERS``).
"""

from __future__ import annotations

import os
import posixpath
import re
import unicodedata
from pathlib import Path

from probos.cognitive.standing_orders import CONSTITUTION_RELATIVE_PATH, constitution_path
```

**2b** (the rule, and the early check in `builder_write_refusal`)

SEARCH:
```python
def _canonical(part: str) -> str:
    """One component in the form a case-insensitive filesystem compares it."""
    return _HFS_IGNORABLE.sub("", part).rstrip(" .").upper()


def builder_write_refusal(
    path_str: str, work_dir: str | os.PathLike[str] | None = None,
) -> str | None:
    """Return why the builder must not write *path_str*, or None if it may.

    *path_str* is relative to *work_dir*. Without *work_dir* only the lexical rules run.
    """
    normalized = path_str.replace("\\", "/")
    if not normalized.strip():
        return "Empty path blocked"
    if ".." in normalized:
```
REPLACE:
```python
def _canonical(part: str) -> str:
    """One component in the form a case-insensitive filesystem compares it."""
    return _HFS_IGNORABLE.sub("", part).rstrip(" .").upper()


# AD-1344 (#1596): the constitution's path components, as written and in canonical form.
_CONSTITUTION_RELATIVE_PARTS = tuple(CONSTITUTION_RELATIVE_PATH.split("/"))
_CONSTITUTION_PARTS = tuple(_canonical(part) for part in _CONSTITUTION_RELATIVE_PARTS)
# A leading drive (``C:``), which a drive-relative path carries before its first component.
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_NOT_A_STR = "Constitution write refused (AD-1344): the path is not an exact str, so it is not checked"


def _exception_name(exc: BaseException) -> str:
    """The class name of *exc* through ``type``'s own descriptor; ``Exception`` under another metaclass."""
    return type(exc).__name__ if type(type(exc)) is type else "Exception"


def _constitution_component(name: str, expected: str) -> bool:
    """Whether canonical *name* is *expected*, or an 8.3 short form with its first two characters."""
    return name == expected or (_SHORT_NAME.search(name) is not None and name[:2] == expected[:2])


def _names_constitution(path_text: str) -> bool:
    """AD-1344: whether *path_text* (an exact ``str``) ends in the constitution's three components.

    Separators become ``/``, a leading drive is dropped and ``..`` is collapsed; each
    component loses any ``:`` suffix (an NTFS stream) and is put in canonical form;
    components then empty (``.``, ``...``) are dropped. What lies above the three is not
    compared, so a copy in another tree matches too.
    """
    unified = _DRIVE_PREFIX.sub("", path_text.replace("\\", "/"), count=1)
    collapsed = posixpath.normpath(unified)
    names = [_canonical(part.split(":", 1)[0]) for part in collapsed.split("/")]
    names = [name for name in names if name]
    tail = names[-len(_CONSTITUTION_PARTS):]
    return len(tail) == len(_CONSTITUTION_PARTS) and all(
        _constitution_component(name, expected) for name, expected in zip(tail, _CONSTITUTION_PARTS)
    )


def _constitution_refusal(path_text: str) -> str:
    return (
        f"Constitution write refused (AD-1344): {path_text!r} is the Federation Constitution "
        f"({CONSTITUTION_RELATIVE_PATH}), which the Captain amends through ordinary "
        "development, not an agent"
    )


def _constitution_unverifiable(path_text: str, stage: str, exc: BaseException) -> str:
    return (
        f"Constitution write refused (AD-1344): cannot verify that {path_text!r} is not the "
        f"Federation Constitution ({stage}: {_exception_name(exc)})"
    )


def _constitution_lexical_refusal(path_text: object) -> str | None:
    """AD-1344: the refusal for a value that is not an exact ``str`` or that names the constitution as written.

    The type is compared first, so no method of a ``str`` subclass or other object runs.
    """
    if type(path_text) is not str:
        return _NOT_A_STR
    if _names_constitution(path_text):
        return _constitution_refusal(path_text)
    return None


def constitution_write_refusal(
    path: str, root: str | os.PathLike[str] | None = None,
) -> str | None:
    """AD-1344 (#1596): why an agent-reachable writer must not write *path*, or None if it may.

    *path* is the path as the writer received it, relative to *root* (the writer's base
    directory) or absolute; a relative *path* with no *root* is taken relative to the
    working directory. Refused, with a one-line reason naming AD-1344: a value that is
    not an exact ``str``; a path whose last three components name the constitution as
    written or once resolved; an existing file with the ``os.stat`` identity of the
    constitution under *root* or of ``standing_orders.constitution_path()``; an
    examination by ``os.stat`` that raises ``OSError`` or ``ValueError`` other than
    ``FileNotFoundError`` or ``NotADirectoryError``; and a resolution that raises
    ``OSError``, ``RuntimeError`` or ``ValueError``. Any other exception propagates.
    """
    lexical = _constitution_lexical_refusal(path)
    if lexical is not None:
        return lexical
    target = Path(path)
    if root is not None and not target.is_absolute():
        target = Path(root) / target
    try:
        resolved = target.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        return _constitution_unverifiable(path, "resolved", exc)
    if _names_constitution(str(resolved)):
        return _constitution_refusal(path)
    candidates = [constitution_path()]
    if root is not None:
        candidates.append(Path(root).joinpath(*_CONSTITUTION_RELATIVE_PARTS))
    for candidate in candidates:
        try:
            constitution = os.stat(candidate)
        except (FileNotFoundError, NotADirectoryError):
            continue  # no constitution there: nothing to alias
        except (OSError, ValueError) as exc:
            return _constitution_unverifiable(path, "constitution", exc)
        try:
            current = os.stat(target)
        except (FileNotFoundError, NotADirectoryError):
            return None  # not on disk, so not a second name of an existing file
        except (OSError, ValueError) as exc:
            return _constitution_unverifiable(path, "target", exc)
        if os.path.samestat(current, constitution):
            return _constitution_refusal(path)
    return None


def builder_write_refusal(
    path_str: str, work_dir: str | os.PathLike[str] | None = None,
) -> str | None:
    """Return why the builder must not write *path_str*, or None if it may.

    *path_str* is relative to *work_dir*. Without *work_dir* only the lexical rules run.
    AD-1344: after the empty-path check, a value that is not an exact ``str`` or that names
    the Federation Constitution is refused with that rule's reason; with *work_dir*,
    ``constitution_write_refusal`` runs after the ``.git`` identity check.
    """
    normalized = path_str.replace("\\", "/")
    if not normalized.strip():
        return "Empty path blocked"
    constitution = _constitution_lexical_refusal(path_str)  # AD-1344: ahead of the rules below, so its reason is given
    if constitution is not None:
        return constitution
    if ".." in normalized:
```

**2c**

SEARCH:
```python
    if work_dir is None:
        return None
    return _git_identity_refusal(parts, path_str, Path(work_dir))
```
REPLACE:
```python
    if work_dir is None:
        return None
    git_refusal = _git_identity_refusal(parts, path_str, Path(work_dir))
    if git_refusal is not None:
        return git_refusal
    return constitution_write_refusal(path_str, work_dir)  # AD-1344: after the .git identity check
```

### Section 3: `src/probos/cognitive/copilot_adapter.py`

No change. `_permission_verdict` (`:322`) calls `builder_write_refusal(rel)` with an exact `str` and no `work_dir`, so the lexical constitution check applies there.

### Section 4: `src/probos/cognitive/swe_harness/tools.py`

**4a**

SEARCH:
```python
from typing import Any, TYPE_CHECKING

from probos.cognitive.standing_orders import (
    is_standing_order_name,
```
REPLACE:
```python
from typing import Any, TYPE_CHECKING

from probos.cognitive.builder_paths import constitution_write_refusal
from probos.cognitive.standing_orders import (
    is_standing_order_name,
```

**4b** (`WriteFileTool.invoke`: the first statement of the existing `try`)

SEARCH:
```python
        if content is None:
            return ToolResult(error="content is required")
        try:
            target = _resolve_path(str(path))
```
REPLACE:
```python
        if content is None:
            return ToolResult(error="content is required")
        try:
            refused = constitution_write_refusal(str(path), _PROJECT_ROOT)  # AD-1344: write_file
            if refused is not None:
                logger.warning("AD-1344 WriteFileTool refused: %s", refused)
                return ToolResult(error=refused)
            target = _resolve_path(str(path))
```

**4c** (`EditFileTool.invoke`: the first statement of the existing `try`)

SEARCH:
```python
        replace_all = bool(params.get("replace_all", False))
        mutation_started = False
        try:
            target = _resolve_path(str(path))
```
REPLACE:
```python
        replace_all = bool(params.get("replace_all", False))
        mutation_started = False
        try:
            refused = constitution_write_refusal(str(path), _PROJECT_ROOT)  # AD-1344: edit_file
            if refused is not None:
                logger.warning("AD-1344 EditFileTool refused: %s", refused)
                return ToolResult(error=refused)
            target = _resolve_path(str(path))
```

### Section 5: `src/probos/agents/file_writer.py`

**5a**

SEARCH:
```python
from probos.substrate.agent import BaseAgent
from probos.types import CapabilityDescriptor, IntentDescriptor, IntentMessage, IntentResult
```
REPLACE:
```python
from probos.cognitive.builder_paths import constitution_write_refusal
from probos.substrate.agent import BaseAgent
from probos.types import CapabilityDescriptor, IntentDescriptor, IntentMessage, IntentResult
```

**5b** (`act`, the proposal: after `Path(path)`, inside the existing `try`)

SEARCH:
```python
            # Validate that the write is feasible
            try:
                p = Path(path)
                parent = p.parent
```
REPLACE:
```python
            # Validate that the write is feasible
            try:
                p = Path(path)
                refused = constitution_write_refusal(str(p), Path.cwd())  # AD-1344: the proposal
                if refused is not None:
                    logger.warning("AD-1344 FileWriterAgent proposal refused: %s", refused)
                    return {"success": False, "error": refused}
                parent = p.parent
```

**5c** (`commit_write`: after `Path(path)`, inside the existing `try`)

SEARCH:
```python
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
```
REPLACE:
```python
        try:
            p = Path(path)
            refused = constitution_write_refusal(str(p), Path.cwd())  # AD-1344: the write
            if refused is not None:
                logger.warning("AD-1344 FileWriterAgent write refused: %s", refused)
                return {"success": False, "error": refused}
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
```

### Section 6: `src/probos/skill_framework.py`

**6a**

SEARCH:
```python
import aiosqlite

from probos.protocols import ConnectionFactory, DatabaseConnection
```
REPLACE:
```python
import aiosqlite

from probos.cognitive.builder_paths import constitution_write_refusal
from probos.protocols import ConnectionFactory, DatabaseConnection
```

**6b** (`create_docx`)

SEARCH:
```python
        if output_path:
            target = Path(os.path.expanduser(output_path))
            target.parent.mkdir(parents=True, exist_ok=True)
            doc.save(str(target))
            return str(target)
```
REPLACE:
```python
        if output_path:
            target = Path(os.path.expanduser(output_path))
            refused = constitution_write_refusal(str(target), Path.cwd())  # AD-1344: docx_create
            if refused is not None:
                logger.warning("AD-1344 DocxAgent refused: %s", refused)
                raise PermissionError(refused)
            target.parent.mkdir(parents=True, exist_ok=True)
            doc.save(str(target))
            return str(target)
```

**6c** (`revise_docx`)

SEARCH:
```python
            raise ValueError("revise_docx requires a .docx file")
        if not source.exists():
            raise FileNotFoundError(file_path)

        doc = Document(str(source))
```
REPLACE:
```python
            raise ValueError("revise_docx requires a .docx file")
        if not source.exists():
            raise FileNotFoundError(file_path)
        refused = constitution_write_refusal(str(source), Path.cwd())  # AD-1344: docx_revise
        if refused is not None:
            logger.warning("AD-1344 DocxAgent refused: %s", refused)
            raise PermissionError(refused)

        doc = Document(str(source))
```

**6d** (`create_pptx`)

SEARCH:
```python
        if output_path:
            target = Path(os.path.expanduser(output_path))
            target.parent.mkdir(parents=True, exist_ok=True)
            deck.save(str(target))
            return str(target)
```
REPLACE:
```python
        if output_path:
            target = Path(os.path.expanduser(output_path))
            refused = constitution_write_refusal(str(target), Path.cwd())  # AD-1344: pptx_create
            if refused is not None:
                logger.warning("AD-1344 PptxAgent refused: %s", refused)
                raise PermissionError(refused)
            target.parent.mkdir(parents=True, exist_ok=True)
            deck.save(str(target))
            return str(target)
```

**6e** (`update_xlsx`)

SEARCH:
```python
            raise ValueError("update_xlsx requires a .xlsx file")
        if not source.exists():
            raise FileNotFoundError(file_path)

        workbook = load_workbook(str(source))
```
REPLACE:
```python
            raise ValueError("update_xlsx requires a .xlsx file")
        if not source.exists():
            raise FileNotFoundError(file_path)
        refused = constitution_write_refusal(str(source), Path.cwd())  # AD-1344: xlsx_update
        if refused is not None:
            logger.warning("AD-1344 XlsxAgent refused: %s", refused)
            raise PermissionError(refused)

        workbook = load_workbook(str(source))
```

### Section 7: `tests/test_bf894_builder_write_boundary.py` (the existing case table gains the neighbours)

SEARCH:
```python
_LEGIT = ("src/probos/x.py", "tests/test_x.py", "config/system.yaml", "docs/a b.md", "conftest.py", ".gitignore", "tests/fixtures/.gitkeep", "tests/-n.py")
```
REPLACE:
```python
# AD-1344 (#1596): the ship and department tiers beside the constitution stay writable.
_LEGIT = ("src/probos/x.py", "tests/test_x.py", "config/system.yaml", "docs/a b.md", "conftest.py", ".gitignore", "tests/fixtures/.gitkeep", "tests/-n.py",
          "config/standing_orders/ship.md", "config/standing_orders/engineering.md")
```

### Section 8: new test file

#### File `tests/test_ad1344_constitution_write_refusal.py`

```python
"""AD-1344 (#1596) S1: agents cannot amend the Federation Constitution.

``builder_paths.constitution_write_refusal`` is the rule. These tests drive it directly (the form
table), then through each writer that calls it: the native build and the test-fix loop
(``execute_approved_build``), the visiting session's permission handler, the SWE-harness
``write_file`` and ``edit_file``, ``FileWriterAgent`` (the proposal, the write, and a bundled
agent's note) and the office document writers. Each refusal is paired with a neighbour the same
writer still writes. Writer tests use paths inside a temporary vessel tree only, so a mutant that
removes a check writes there; forms outside the tree are judged by the rule alone, and the UNC
form only by the lexical checks. An autouse guard snapshots the repository's own constitution
(bytes and mode) and compares it after each test. Two AST censuses over tracked files pin the
inventory: which functions call the rule, and the file-write calls in the agent-facing modules
with a classification for each.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.agents.file_writer import FileWriterAgent
from probos.agents.utility.organizer_agents import _mesh_write_file
from probos.cognitive import builder as builder_module
from probos.cognitive import builder_paths, standing_orders
from probos.cognitive.builder import BuildSpec, execute_approved_build
from probos.cognitive.builder_paths import (
    builder_write_refusal,
    constitution_write_refusal,
    fix_loop_write_refusal,
)
from probos.cognitive.copilot_adapter import build_session_permission_handler
from probos.cognitive.standing_orders import (
    CONSTITUTION_FILENAME,
    CONSTITUTION_RELATIVE_PATH,
    constitution_path,
    standing_orders_dir,
)
from probos.cognitive.swe_harness import tools as swe_tools
from probos.cognitive.swe_harness.tools import EditFileTool, WriteFileTool
from probos.skill_framework import DocxAgent, PptxAgent, XlsxAgent
from probos.types import IntentMessage

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REAL_CONSTITUTION = _REPO_ROOT / "config" / "standing_orders" / "federation.md"
_AD = "AD-1344"
_ORIGINAL = "# Federation Constitution\nCONSTITUTION v1\n"
_SHIP = "# Ship Standing Orders\nSHIP v1\n"
_POINTER = "gitdir: ../elsewhere/.git/worktrees/wt\n"


# ── Fixtures and helpers ──────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _real_constitution_untouched():
    """The repository's own constitution is unchanged by each test (a snapshot, not a frozen hash).

    The file is named by a literal path, not through ``constitution_path()``: a break in that function
    must fail the ownership test (T1), not make every test in this file error in its setup.
    """
    before = (_REAL_CONSTITUTION.read_bytes(), os.stat(_REAL_CONSTITUTION).st_mode)
    yield
    after = (_REAL_CONSTITUTION.read_bytes(), os.stat(_REAL_CONSTITUTION).st_mode)
    assert after == before, "the repository's constitution changed"


@pytest.fixture
def vessel(tmp_path: Path) -> Path:
    root = tmp_path / "vessel"
    orders = root / "config" / "standing_orders"
    orders.mkdir(parents=True)
    (orders / CONSTITUTION_FILENAME).write_text(_ORIGINAL, encoding="utf-8")
    (orders / "ship.md").write_text(_SHIP, encoding="utf-8")
    (root / "config" / "other.yaml").write_text("other: 1\n", encoding="utf-8")
    (root / "docs").mkdir()
    return root


@pytest.fixture
def swe_root(vessel: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(swe_tools, "_PROJECT_ROOT", vessel)
    return vessel


def _constitution(root: Path) -> Path:
    return root.joinpath(*CONSTITUTION_RELATIVE_PATH.split("/"))


def _unchanged(root: Path) -> bool:
    return _constitution(root).read_text(encoding="utf-8") == _ORIGINAL


def _hard_link(root: Path, name: str) -> Path:
    alias = root / "docs" / name
    try:
        os.link(_constitution(root), alias)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"hard links are unavailable here: {exc}")
    assert os.path.samefile(alias, _constitution(root)), "premise: the link is the constitution"
    return alias


def _dir_link(link: Path, target: Path) -> None:
    """A directory link: a junction on Windows (no privilege needed), a symlink elsewhere."""
    try:
        if os.name == "nt":
            import _winapi

            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError, AttributeError) as exc:
        pytest.skip(f"directory links are unavailable here: {exc}")


def _kind_of(result: object) -> object:
    return result["kind"] if isinstance(result, dict) else result.kind  # type: ignore[union-attr]


# ── The forms ─────────────────────────────────────────────────────────────

# Relative to a writer's root: safe to drive through a real writer rooted in the vessel.
_IN_TREE = {
    "exact": "config/standing_orders/federation.md",
    "case": "CONFIG/Standing_Orders/FEDERATION.MD",
    "backslashes": "config\\standing_orders\\federation.md",
    "dot-prefix": "./config/standing_orders/federation.md",
    "dot-component": "config/./standing_orders/federation.md",
    "empty-component": "config//standing_orders/federation.md",
    "dots-only-component": "config/standing_orders/.../federation.md",
    "dot-dot": "config/standing_orders/notes/../federation.md",
    "trailing-dot": "config/standing_orders/federation.md.",
    "trailing-space": "config/standing_orders/federation.md ",
    "default-stream": "config/standing_orders/federation.md::$DATA",
    "named-stream": "config/standing_orders/federation.md:hidden",
    "short-name-file": "config/standing_orders/FEDERA~1.MD",
    "short-name-directory": "config/STANDI~1/federation.md",
    "hfs-ignorable": "config/standing_orders/fede\u200cration.md",
}
# Outside any test tree: judged by the rule alone, never through a writer.
_OUT_OF_TREE = {
    "windows-absolute": "C:/Users/x/ProbOS/config/standing_orders/federation.md",
    "posix-absolute": "/home/x/ProbOS/config/standing_orders/federation.md",
    "extended-length": "\\\\?\\C:\\ProbOS\\config\\standing_orders\\federation.md",
    "another-worktree": "D:/ProbOS-worktrees/wt/config/standing_orders/federation.md",
    "drive-relative": "C:config/standing_orders/federation.md",
}
# A network form: judged only where nothing is resolved (no host is contacted).
_LEXICAL_ONLY = {"unc": "\\\\server\\share\\ProbOS\\config\\standing_orders\\federation.md"}
_REFUSED = {**_IN_TREE, **_OUT_OF_TREE}
_LEXICAL = {**_REFUSED, **_LEXICAL_ONLY}
_NEIGHBOURS = [
    "config/standing_orders/ship.md",
    "config/standing_orders/engineering.md",
    "config/standing_orders/federation.md.bak",
    "config/standing_orders/federation_notes.md",
    "config/standing_orders/notes/federation.md",
    "config/federation.md",
    "config/standing_orders",
    "config",
    "config/system.yaml",
    "src/probos/federation.md",
]


# ── 1. Ownership ──────────────────────────────────────────────────────────


def test_the_standing_orders_module_owns_the_constitution_path() -> None:
    """T1: the literal location, which the fix loop cannot edit (it cannot write tests/)."""
    assert CONSTITUTION_RELATIVE_PATH == "config/standing_orders/federation.md"
    assert CONSTITUTION_FILENAME == "federation.md"
    assert constitution_path() == standing_orders_dir() / "federation.md"
    root = Path(standing_orders.__file__).resolve().parents[3]
    assert constitution_path() == root / "config" / "standing_orders" / "federation.md"
    assert constitution_path().is_file(), "premise: this checkout carries its constitution"


def test_the_composer_reads_the_constitution_through_the_constant(vessel: Path) -> None:
    """T2: the personnel-record tiers and the composed instructions both read the file."""
    orders = vessel / "config" / "standing_orders"
    tiers = standing_orders.get_order_tiers("builder", orders_dir=orders)
    assert tiers[0] == {
        "tier": "federation", "source_file": CONSTITUTION_FILENAME, "present": True, "text": _ORIGINAL.strip(),
    }
    composed = standing_orders.compose_instructions("builder", "", orders_dir=orders)
    assert "CONSTITUTION v1" in composed


# ── 2. The form table ─────────────────────────────────────────────────────


@pytest.mark.parametrize("path", list(_REFUSED.values()), ids=list(_REFUSED))
def test_the_rule_refuses_every_form_of_the_constitution(path: str) -> None:
    """T3."""
    refusal = constitution_write_refusal(path)
    assert refusal is not None and _AD in refusal
    assert "\n" not in refusal and repr(path) in refusal


@pytest.mark.parametrize("path", _NEIGHBOURS)
def test_the_rule_allows_the_neighbours(path: str) -> None:
    """T4."""
    assert constitution_write_refusal(path) is None


@pytest.mark.parametrize("path", list(_LEXICAL.values()), ids=list(_LEXICAL))
def test_the_builder_boundary_refuses_every_form_with_this_ads_reason(path: str) -> None:
    """T5: lexical only (no work_dir), so the AD-1344 reason can come only from the early check."""
    refusal = builder_write_refusal(path)
    assert refusal is not None and _AD in refusal


@pytest.mark.parametrize("path", _NEIGHBOURS)
def test_the_builder_boundary_allows_the_neighbours(path: str) -> None:
    """T6."""
    assert builder_write_refusal(path) is None


@pytest.mark.parametrize("path", list(_LEXICAL.values()), ids=list(_LEXICAL))
def test_the_fix_loop_refuses_every_form_with_this_ads_reason(path: str) -> None:
    """T7."""
    refusal = fix_loop_write_refusal(path)
    assert refusal is not None and _AD in refusal


def test_a_value_that_is_not_an_exact_str_is_refused_without_running_its_code(vessel: Path) -> None:
    """T8."""
    ran: list[str] = []

    class Spy(str):
        def replace(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            ran.append("replace")
            return str.replace(self, *args, **kwargs)

        def split(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            ran.append("split")
            return str.split(self, *args, **kwargs)

        def __fspath__(self) -> str:
            ran.append("__fspath__")
            return str.__str__(self)

        def __repr__(self) -> str:
            ran.append("__repr__")
            return str.__repr__(self)

    neighbour = Spy("config/standing_orders/ship.md")
    refusal = constitution_write_refusal(neighbour, vessel)
    assert refusal is not None and _AD in refusal and "exact str" in refusal
    assert ran == [], f"the rule ran code of the caller's value: {ran}"
    assert constitution_write_refusal(str.__str__(neighbour), vessel) is None  # control: the same text, exact str
    builder_refusal = builder_write_refusal(Spy(CONSTITUTION_RELATIVE_PATH))
    assert builder_refusal is not None and "exact str" in builder_refusal


# ── 3. Identity, links and failing closed ─────────────────────────────────


def test_a_hard_link_to_the_constitution_is_refused_under_the_writers_root(vessel: Path) -> None:
    """T9."""
    alias = _hard_link(vessel, "alias.md")
    assert builder_write_refusal("docs/alias.md") is None, "premise: no lexical rule names it"
    refusal = constitution_write_refusal("docs/alias.md", vessel)
    assert refusal is not None and _AD in refusal
    assert constitution_write_refusal(str(alias), vessel) is not None
    (vessel / "docs" / "other.md").write_text("x", encoding="utf-8")
    assert constitution_write_refusal("docs/other.md", vessel) is None  # an existing unrelated file
    assert constitution_write_refusal("docs/new.md", vessel) is None  # not on disk yet
    assert constitution_write_refusal("config/standing_orders/ship.md", vessel) is None


def test_a_hard_link_to_the_running_checkouts_constitution_is_refused_without_a_root(
    vessel: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T10."""
    alias = _hard_link(vessel, "alias.md")
    assert constitution_write_refusal(str(alias)) is None, "premise: the running checkout's constitution is another file"
    monkeypatch.setattr(standing_orders, "_DEFAULT_ORDERS_DIR", vessel / "config" / "standing_orders")
    assert constitution_path() == _constitution(vessel), "premise: the checkout is now the vessel"
    refusal = constitution_write_refusal(str(alias))
    assert refusal is not None and _AD in refusal


def test_a_missing_checkout_constitution_still_checks_the_writers_root(
    vessel: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T11."""
    alias = _hard_link(vessel, "alias.md")
    empty = tmp_path / "empty_orders"
    empty.mkdir()
    monkeypatch.setattr(standing_orders, "_DEFAULT_ORDERS_DIR", empty)
    assert not constitution_path().exists(), "premise: the checkout's constitution is missing"
    refusal = constitution_write_refusal(str(alias), vessel)
    assert refusal is not None and _AD in refusal


def test_a_directory_link_into_the_constitutions_directory_is_refused_when_the_file_is_missing(vessel: Path) -> None:
    """T12: identity has nothing to compare, so only the resolved name refuses."""
    _constitution(vessel).unlink()
    _dir_link(vessel / "docs" / "orders", vessel / "config" / "standing_orders")
    assert builder_write_refusal("docs/orders/federation.md") is None, "premise: the written name is not the constitution"
    refusal = constitution_write_refusal("docs/orders/federation.md", vessel)
    assert refusal is not None and _AD in refusal
    assert constitution_write_refusal("docs/orders/ship.md", vessel) is None


def test_a_constitution_that_cannot_be_examined_refuses_the_write(vessel: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T13."""
    assert constitution_write_refusal("docs/new.md", vessel) is None, "premise: accepted before the patch"
    real_stat = os.stat

    def _stat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if Path(path).name == CONSTITUTION_FILENAME:
            raise PermissionError(13, "denied")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(builder_paths.os, "stat", _stat)
    refusal = constitution_write_refusal("docs/new.md", vessel)
    monkeypatch.undo()
    assert refusal is not None and _AD in refusal and "(constitution: PermissionError)" in refusal


def test_a_target_that_cannot_be_examined_is_refused(vessel: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T14."""
    (vessel / "docs" / "other.md").write_text("x", encoding="utf-8")
    assert constitution_write_refusal("docs/other.md", vessel) is None, "premise: accepted before the patch"
    real_stat = os.stat

    def _stat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if Path(path).name == "other.md":
            raise PermissionError(13, "denied")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(builder_paths.os, "stat", _stat)
    refusal = constitution_write_refusal("docs/other.md", vessel)
    monkeypatch.undo()
    assert refusal is not None and "(target: PermissionError)" in refusal


def test_a_failure_under_another_metaclass_is_named_exception(vessel: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T15: the reason reads no attribute of a class whose metaclass is not exactly ``type``."""
    ran: list[str] = []

    class Meta(type):
        @property
        def __name__(cls) -> str:  # type: ignore[override]
            ran.append("__name__")
            return "Spoofed"

    class Denied(PermissionError, metaclass=Meta):
        pass

    (vessel / "docs" / "other.md").write_text("x", encoding="utf-8")
    real_stat = os.stat

    def _stat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if Path(path).name == "other.md":
            raise Denied(13, "denied")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(builder_paths.os, "stat", _stat)
    refusal = constitution_write_refusal("docs/other.md", vessel)
    monkeypatch.undo()
    assert refusal is not None and "(target: Exception)" in refusal
    assert ran == [], "the metaclass's __name__ ran"


def test_a_path_that_cannot_be_resolved_is_refused(vessel: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T16."""
    assert constitution_write_refusal("docs/probe.md", vessel) is None, "premise: accepted before the patch"
    real_resolve = Path.resolve

    def resolve(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.name == "probe.md":
            raise ValueError("unresolvable")
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    refusal = constitution_write_refusal("docs/probe.md", vessel)
    monkeypatch.undo()
    assert refusal is not None and _AD in refusal and "(resolved: ValueError)" in refusal


def test_a_refusal_changes_nothing_on_disk_and_a_direct_write_still_works(vessel: Path) -> None:
    """T17: no friction. The rule does not lock, chmod or mark the file; a direct write is untouched."""
    fed = _constitution(vessel)
    before = (fed.read_bytes(), os.stat(fed).st_mode)
    assert constitution_write_refusal(CONSTITUTION_RELATIVE_PATH, vessel) is not None
    assert (fed.read_bytes(), os.stat(fed).st_mode) == before
    fed.write_text("CONSTITUTION v2\n", encoding="utf-8")
    assert fed.read_text(encoding="utf-8") == "CONSTITUTION v2\n"


# ── 4. The builder's writers ──────────────────────────────────────────────


def _no_real_git(stack: ExitStack) -> AsyncMock:
    for name, value in (("_git_current_branch", "main"), ("_is_dirty_working_tree", False),
                        ("_git_create_branch", (True, "builder-ad1344")), ("_git_return_to", (True, "ok")),
                        ("_run_git", (0, "", ""))):
        stack.enter_context(patch.object(builder_module, name, AsyncMock(return_value=value)))
    commit = AsyncMock(return_value=(True, "abc123"))
    stack.enter_context(patch.object(builder_module, "_git_add_and_commit", commit))
    return commit


def _create(path: str, content: str) -> dict:
    return {"path": path, "content": content, "mode": "create", "after_line": None}


async def _build(vessel: Path, changes: list[dict]) -> tuple[object, AsyncMock]:
    (vessel / ".git").write_text(_POINTER, encoding="utf-8")
    with ExitStack() as stack:
        commit = _no_real_git(stack)
        result = await execute_approved_build(changes, BuildSpec(title="AD-1344 probe", description=""), str(vessel), run_tests=False)
    return result, commit


@pytest.mark.parametrize("form", ["exact", "case", "backslashes", "dot-prefix"])
async def test_the_native_build_refuses_the_constitution(vessel: Path, form: str) -> None:
    """T18."""
    result, commit = await _build(vessel, [_create(_IN_TREE[form], "AMENDED\n")])
    assert _unchanged(vessel)
    assert result.files_written == [] and _AD in result.error
    commit.assert_not_awaited()


async def test_the_native_build_refuses_a_hard_link_to_the_constitution(vessel: Path) -> None:
    """T19."""
    _hard_link(vessel, "alias.md")
    result, commit = await _build(vessel, [_create("docs/alias.md", "AMENDED\n")])
    assert _unchanged(vessel) and _AD in result.error
    commit.assert_not_awaited()


async def test_the_native_build_still_modifies_the_ship_tier(vessel: Path) -> None:
    """T20."""
    change = {"path": "config/standing_orders/ship.md", "mode": "modify",
              "replacements": [{"search": "SHIP v1", "replace": "SHIP v2"}]}
    result, commit = await _build(vessel, [change])
    assert not result.error, result.error
    assert (vessel / "config" / "standing_orders" / "ship.md").read_text(encoding="utf-8") == "# Ship Standing Orders\nSHIP v2\n"
    assert "config/standing_orders/ship.md" in commit.await_args.args[0]


async def test_the_fix_loop_refuses_a_repair_of_the_constitution(vessel: Path) -> None:
    """T21."""
    (vessel / ".git").write_text(_POINTER, encoding="utf-8")
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=MagicMock(content=f"===FILE: {CONSTITUTION_RELATIVE_PATH}===\nAMENDED\n===END FILE===\n"))
    with ExitStack() as stack:
        _no_real_git(stack)
        stack.enter_context(patch.object(builder_module, "_run_targeted_tests", AsyncMock(return_value=(False, "1 failed", []))))
        result = await execute_approved_build([_create("ok.py", "x = 1\n")], BuildSpec(title="AD-1344 repair", description=""),
                                              str(vessel), run_tests=True, max_fix_attempts=1, llm_client=llm)
    fix_calls = sum("Test Fix Required" in call.args[0].prompt for call in llm.complete.await_args_list)
    assert fix_calls == 1, "premise: the repair loop ran and received the block"
    assert _unchanged(vessel) and _AD in result.error


def test_the_visiting_session_refuses_a_write_to_the_constitution(tmp_path: Path) -> None:
    """T22."""
    session = tmp_path / "session"
    session.mkdir()
    handler = build_session_permission_handler(str(session), ("standing_orders_lookup",))

    def ask(name: str) -> object:
        return _kind_of(handler({"kind": "write", "fileName": name}, {}))

    assert ask("config/standing_orders/ship.md") == "approved"  # controls first
    assert ask(str(session / "config" / "other.yaml")) == "approved"
    assert ask(CONSTITUTION_RELATIVE_PATH) == "denied-by-rules"
    assert ask(str(session / "config" / "standing_orders" / "federation.md")) == "denied-by-rules"
    assert ask("config/standing_orders/FEDERATION.MD") == "denied-by-rules"


# ── 5. SWE harness ────────────────────────────────────────────────────────


@pytest.mark.parametrize("path", list(_IN_TREE.values()), ids=list(_IN_TREE))
async def test_write_file_refuses_the_constitution(swe_root: Path, path: str) -> None:
    """T23."""
    result = await WriteFileTool(SimpleNamespace()).invoke({"path": path, "content": "AMENDED\n"})
    assert not result.success and _AD in (result.error or "")
    assert _unchanged(swe_root)


async def test_write_file_refuses_absolute_paths_and_still_writes_the_neighbours(swe_root: Path) -> None:
    """T24."""
    tool = WriteFileTool(SimpleNamespace())
    for path in (str(_constitution(swe_root)), f"{swe_root}/CONFIG/Standing_Orders/FEDERATION.MD"):
        result = await tool.invoke({"path": path, "content": "AMENDED\n"})
        assert not result.success and _AD in (result.error or ""), path
    assert _unchanged(swe_root)
    for rel, text in (("config/standing_orders/ship.md", "SHIP v2\n"), ("config/other.yaml", "other: 2\n"),
                      ("config/standing_orders/federation_notes.md", "notes\n")):
        result = await tool.invoke({"path": rel, "content": text})
        assert result.success, f"{rel}: {result.error}"
        assert (swe_root / rel).read_text(encoding="utf-8") == text


async def test_write_file_refuses_a_hard_link_and_a_directory_link(swe_root: Path) -> None:
    """T25."""
    _hard_link(swe_root, "alias.md")
    tool = WriteFileTool(SimpleNamespace())
    linked = await tool.invoke({"path": "docs/alias.md", "content": "AMENDED\n"})
    assert not linked.success and _AD in (linked.error or "")
    _dir_link(swe_root / "docs" / "orders", swe_root / "config" / "standing_orders")
    through = await tool.invoke({"path": "docs/orders/federation.md", "content": "AMENDED\n"})
    assert not through.success and _AD in (through.error or "")
    assert _unchanged(swe_root)


async def test_write_file_refuses_under_the_effect_broker_context(swe_root: Path) -> None:
    """T26: the refusal comes before the strict-native lock and the plain write alike."""
    context = {
        "_effect_dispatch_context": object(),
        "_strict_native_target": str(_constitution(swe_root)),
        "_strict_native_root": str(swe_root),
    }
    result = await WriteFileTool(SimpleNamespace()).invoke({"path": CONSTITUTION_RELATIVE_PATH, "content": "AMENDED\n"}, context)
    assert not result.success and _AD in (result.error or "")
    assert _unchanged(swe_root)


@pytest.mark.parametrize("path", list(_IN_TREE.values()), ids=list(_IN_TREE))
async def test_edit_file_refuses_the_constitution(swe_root: Path, path: str) -> None:
    """T27."""
    result = await EditFileTool(SimpleNamespace()).invoke({"path": path, "old_text": "CONSTITUTION v1", "new_text": "AMENDED"})
    assert not result.success and _AD in (result.error or "")
    assert _unchanged(swe_root)


async def test_edit_file_refuses_a_hard_link_and_still_edits_the_ship_tier(swe_root: Path) -> None:
    """T28."""
    tool = EditFileTool(SimpleNamespace())
    ship = await tool.invoke({"path": "config/standing_orders/ship.md", "old_text": "SHIP v1", "new_text": "SHIP v2"})
    assert ship.success and ship.output["replacements"] == 1, f"control: {ship.error}"
    _hard_link(swe_root, "alias.md")
    result = await tool.invoke({"path": "docs/alias.md", "old_text": "CONSTITUTION v1", "new_text": "AMENDED"})
    assert not result.success and _AD in (result.error or "")
    assert _unchanged(swe_root)


# ── 6. FileWriterAgent ────────────────────────────────────────────────────


async def test_file_writer_refuses_the_proposal_and_the_commit(vessel: Path) -> None:
    """T29."""
    agent = FileWriterAgent(pool="filesystem")
    await agent.start()
    fed = str(_constitution(vessel))
    ship = str(vessel / "config" / "standing_orders" / "ship.md")
    proposal = await agent.handle_intent(IntentMessage(intent="write_file", params={"path": fed, "content": "AMENDED\n"}))
    assert proposal is not None and proposal.success is False and _AD in (proposal.error or "")
    control = await agent.handle_intent(IntentMessage(intent="write_file", params={"path": ship, "content": "SHIP v2\n"}))
    assert control is not None and control.success is True and control.result["requires_consensus"] is True
    committed = await FileWriterAgent.commit_write(fed, "AMENDED\n")
    assert committed["success"] is False and _AD in committed["error"]
    assert (await FileWriterAgent.commit_write(ship, "SHIP v2\n"))["success"] is True
    assert _unchanged(vessel)


async def test_file_writer_commit_refuses_a_hard_link_under_its_working_directory(
    vessel: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T30."""
    alias = _hard_link(vessel, "alias.md")
    assert constitution_write_refusal(str(alias), _REPO_ROOT) is None, "premise: only the vessel's constitution matches"
    monkeypatch.chdir(vessel)
    committed = await FileWriterAgent.commit_write(str(alias), "AMENDED\n")
    assert committed["success"] is False and _AD in committed["error"]
    assert _unchanged(vessel)


async def test_a_bundled_agents_note_cannot_reach_the_constitution(vessel: Path) -> None:
    """T31: the notes agent joins a model-chosen filename to its directory and calls commit_write."""
    notes_dir = vessel / "home" / "notes"
    notes_dir.mkdir(parents=True)
    assert not await _mesh_write_file(None, f"{notes_dir}/../../config/standing_orders/federation.md", "AMENDED\n")
    assert _unchanged(vessel)
    assert await _mesh_write_file(None, f"{notes_dir}/note.md", "a note\n")
    assert (notes_dir / "note.md").read_text(encoding="utf-8") == "a note\n"


# ── 7. Office document writers ────────────────────────────────────────────


async def test_office_create_refuses_the_constitution(vessel: Path) -> None:
    """T32."""
    docx = DocxAgent(pool="office")
    with pytest.raises(PermissionError, match=_AD):
        await docx.handle_intent(IntentMessage(intent="docx_create", params={
            "title": "Amendment", "content": ["x"], "output_path": str(_constitution(vessel))}))
    with pytest.raises(PermissionError, match=_AD):
        await PptxAgent(pool="office").handle_intent(IntentMessage(intent="pptx_create", params={
            "title": "Amendment", "slides": [{"title": "x", "bullets": ["y"]}], "output_path": str(_constitution(vessel))}))
    assert _unchanged(vessel)
    notes = vessel / "config" / "standing_orders" / "notes.docx"
    control = await docx.handle_intent(IntentMessage(intent="docx_create", params={
        "title": "Notes", "content": ["x"], "output_path": str(notes)}))
    assert control is not None and control.success is True and notes.is_file()


async def test_office_revise_and_update_refuse_a_link_to_the_constitution(
    vessel: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T33."""
    docx_alias = _hard_link(vessel, "constitution.docx")
    xlsx_alias = _hard_link(vessel, "constitution.xlsx")
    monkeypatch.chdir(vessel)
    with pytest.raises(PermissionError, match=_AD):
        await DocxAgent(pool="office").handle_intent(IntentMessage(intent="docx_revise", params={
            "file_path": str(docx_alias), "instructions": "amend"}))
    with pytest.raises(PermissionError, match=_AD):
        await XlsxAgent(pool="office").handle_intent(IntentMessage(intent="xlsx_update", params={
            "file_path": str(xlsx_alias), "sheet": "Sheet", "updates": {"A1": "amended"}}))
    assert _unchanged(vessel)
    notes = vessel / "config" / "standing_orders" / "notes.docx"
    await DocxAgent(pool="office").create_docx(title="Notes", content=["x"], output_path=str(notes))
    revised = await DocxAgent(pool="office").handle_intent(IntentMessage(intent="docx_revise", params={
        "file_path": str(notes), "instructions": "tidy"}))
    assert revised is not None and revised.success is True


# ── 8. The inventory (AST censuses over tracked files) ────────────────────

_GUARD = "constitution_write_refusal"
_LEXICAL_HELPERS = frozenset({"_names_constitution", "_constitution_lexical_refusal"})
_EXPECTED_CALLERS = {
    ("src/probos/cognitive/builder_paths.py", "builder_write_refusal"),
    ("src/probos/cognitive/swe_harness/tools.py", "WriteFileTool.invoke"),
    ("src/probos/cognitive/swe_harness/tools.py", "EditFileTool.invoke"),
    ("src/probos/agents/file_writer.py", "FileWriterAgent.act"),
    ("src/probos/agents/file_writer.py", "FileWriterAgent.commit_write"),
    ("src/probos/skill_framework.py", "DocxAgent.create_docx"),
    ("src/probos/skill_framework.py", "DocxAgent.revise_docx"),
    ("src/probos/skill_framework.py", "PptxAgent.create_pptx"),
    ("src/probos/skill_framework.py", "XlsxAgent.update_xlsx"),
}
_CENSUS_SCOPE = (
    "src/probos/agents", "src/probos/tools", "src/probos/cognitive/swe_harness",
    "src/probos/skill_framework.py", "src/probos/cognitive/builder.py", "src/probos/cognitive/copilot_adapter.py",
    "src/probos/cognitive/skill_forge.py", "src/probos/cognitive/skill_catalog.py",
)
_GUARDS = frozenset({"constitution_write_refusal", "builder_write_refusal", "fix_loop_write_refusal"})
_METHOD_WRITES = frozenset({"write_text", "write_bytes", "unlink", "rename", "touch", "rmdir", "symlink_to", "hardlink_to", "save"})
_OS_WRITES = frozenset({"remove", "unlink", "rename", "replace", "link", "symlink", "rmdir", "removedirs", "truncate"})
_MODULE_WRITES = {
    "os": _OS_WRITES,
    "_os": _OS_WRITES,
    "shutil": frozenset({"copy", "copy2", "copyfile", "copytree", "move", "rmtree"}),
}
_GUARDED = "guarded"
_RESTORE = "BF-904a restore: writes back bytes a build saved before its first write to an admitted path, and removes what that build created"
_VAULT = "the credential vault's own file (constructor-injected)"
_RECORDINGS = "expired recordings under the recordings directory"
_WRITE_SITES: dict[tuple[str, str, str], str] = {
    ("src/probos/agents/file_writer.py", "FileWriterAgent.commit_write", ".write_text"): _GUARDED,
    ("src/probos/agents/http_fetch.py", "HttpFetchAgent._record_to_profile", ".save"): "a domain-profile store record, not a file path",
    ("src/probos/agents/utility/avatar_agents.py", "AvatarRendererAgent.act", "os.replace"): "the avatar store; the target is <agent_id>.vrm, not a .md file",
    ("src/probos/cognitive/builder.py", "_restore_pre_build_files", ".rmdir"): _RESTORE,
    ("src/probos/cognitive/builder.py", "_restore_pre_build_files", ".unlink"): _RESTORE,
    ("src/probos/cognitive/builder.py", "_restore_pre_build_files", ".write_bytes"): _RESTORE,
    ("src/probos/cognitive/builder.py", "execute_approved_build", ".write_text"): _GUARDED,
    ("src/probos/cognitive/copilot_adapter.py", "seed_session_directory", ".write_text"): "the build's own session directory; its writes reach the tree through execute_approved_build",
    ("src/probos/cognitive/skill_catalog.py", "CognitiveSkillCatalog._rewrite_frontmatter", ".write_text"): "the SKILL.md of a cataloged skill directory",
    ("src/probos/cognitive/skill_catalog.py", "CognitiveSkillCatalog.import_skill", "shutil.copytree"): "copytree creates its destination and raises on an existing one, so it replaces no file",
    ("src/probos/cognitive/skill_catalog.py", "CognitiveSkillCatalog.remove_skill", "shutil.rmtree"): "a cataloged skill's directory; called from the Captain's skill command (commands_skill.py:293)",
    ("src/probos/cognitive/skill_forge.py", "SkillForge._write_files", ".write_text"): "under the forge's staging directory (resolved containment check, skill_forge.py:305-315)",
    ("src/probos/cognitive/skill_forge.py", "SkillForge.forge", "shutil.rmtree"): "the forge's own staging directory",
    ("src/probos/cognitive/swe_harness/tools.py", "EditFileTool.invoke", ".write_text"): _GUARDED,
    ("src/probos/cognitive/swe_harness/tools.py", "WriteFileTool.invoke", ".write_text"): _GUARDED,
    ("src/probos/skill_framework.py", "DocxAgent.create_docx", ".save"): _GUARDED,
    ("src/probos/skill_framework.py", "DocxAgent.revise_docx", ".save"): _GUARDED,
    ("src/probos/skill_framework.py", "PptxAgent.create_pptx", ".save"): _GUARDED,
    ("src/probos/skill_framework.py", "XlsxAgent.update_xlsx", ".save"): _GUARDED,
    ("src/probos/tools/browser/actions.py", "_action_upload_file", "_os.unlink"): "the temporary credential file this action materialized",
    ("src/probos/tools/browser/credentials.py", "EncryptedFileCredentialVault._save", "open"): _VAULT,
    ("src/probos/tools/browser/credentials.py", "EncryptedFileCredentialVault._save", "os.replace"): _VAULT,
    ("src/probos/tools/browser/credentials.py", "EncryptedFileCredentialVault.materialize_to_temp", "os.unlink"): "a temporary file this vault created",
    ("src/probos/tools/browser/recording_reaper.py", "RecordingReaper._reap_sync", ".rmdir"): _RECORDINGS,
    ("src/probos/tools/browser/recording_reaper.py", "RecordingReaper._reap_sync", ".unlink"): _RECORDINGS,
    ("src/probos/tools/code_execution_tool.py", "CodeExecutionTool._stage_thread_artifacts", ".write_bytes"): "thread attachments staged into the run's own temporary work directory",
    ("src/probos/tools/code_execution_tool.py", "CodeExecutionTool._start_fetch_broker", ".write_text"): "the sandbox helper in the run's own temporary work directory",
    ("src/probos/tools/code_execution_tool.py", "CodeExecutionTool.invoke", "shutil.rmtree"): "the run's own temporary work directory",
}
_CHANNEL_SUFFIXES = (".py", ".ps1", ".sh", ".yml", ".yaml", ".toml", ".cfg")


def _tracked(*specs: str) -> list[str]:
    if shutil.which("git") is None:
        pytest.skip("git is not installed; the census reads tracked files only")
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--", *specs], cwd=_REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return sorted(path for path in listing.split("\0") if path)


def _calls(source: str) -> list[tuple[str, ast.Call]]:
    """Every call, with the qualified name of the innermost function holding it ("<module>" at top level)."""
    found: list[tuple[str, ast.Call]] = []

    def visit(node: ast.AST, scope: str, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, scope, f"{prefix}{child.name}.")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{child.name}"
                visit(child, name, f"{name}.")
            else:
                if isinstance(child, ast.Call):
                    found.append((scope, child))
                visit(child, scope, prefix)

    visit(ast.parse(source), "<module>", "")
    return found


def _callee(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else ""


def _opens_for_writing(mode: ast.AST | None) -> bool:
    if mode is None:
        return False
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return any(flag in mode.value for flag in "wax+")
    return True  # a mode the census cannot read is counted


def _write_primitive(call: ast.Call) -> str | None:
    func = call.func
    keyword_mode = next((kw.value for kw in call.keywords if kw.arg == "mode"), None)
    if isinstance(func, ast.Name) and func.id == "open":
        return "open" if _opens_for_writing(call.args[1] if len(call.args) > 1 else keyword_mode) else None
    if not isinstance(func, ast.Attribute):
        return None
    owner = func.value.id if isinstance(func.value, ast.Name) else None
    if owner in _MODULE_WRITES:
        return f"{owner}.{func.attr}" if func.attr in _MODULE_WRITES[owner] else None
    if func.attr in _METHOD_WRITES:
        return f".{func.attr}"
    if func.attr == "open":
        return ".open" if _opens_for_writing(call.args[0] if call.args else keyword_mode) else None
    return None


def _source(rel: str) -> str:
    return (_REPO_ROOT / rel).read_text(encoding="utf-8-sig")


def test_the_rule_is_called_by_the_inventoried_writers_and_its_helpers_stay_private() -> None:
    """T34 (census A)."""
    callers: set[tuple[str, str]] = set()
    helper_files: set[str] = set()
    for rel in _tracked("src/probos"):
        if not rel.endswith(".py"):
            continue
        for scope, call in _calls(_source(rel)):
            name = _callee(call)
            if name == _GUARD:
                callers.add((rel, scope))
            elif name in _LEXICAL_HELPERS:
                helper_files.add(rel)
    assert callers == _EXPECTED_CALLERS
    assert helper_files == {"src/probos/cognitive/builder_paths.py"}, "the lexical-only helpers are the boundary's own"


def test_every_write_in_the_agent_facing_modules_is_guarded_or_classified() -> None:
    """T35 (census B)."""
    found: set[tuple[str, str, str]] = set()
    guarded: set[tuple[str, str]] = set()
    for rel in _tracked(*_CENSUS_SCOPE):
        if not rel.endswith(".py"):
            continue
        for scope, call in _calls(_source(rel)):
            primitive = _write_primitive(call)
            if primitive is not None:
                found.add((rel, scope, primitive))
            if _callee(call) in _GUARDS:
                guarded.add((rel, scope))
    new = sorted(found - set(_WRITE_SITES))
    stale = sorted(set(_WRITE_SITES) - found)
    assert not new, (
        f"unclassified write sites: {new}. Call builder_paths.constitution_write_refusal before the "
        "write, or add a row naming why the path cannot be the constitution"
    )
    assert not stale, f"stale rows (the write moved or went): {stale}"
    unguarded = sorted(key for key, why in _WRITE_SITES.items() if why == _GUARDED and key[:2] not in guarded)
    assert not unguarded, f"rows marked guarded whose function calls no guard: {unguarded}"


def test_the_captains_channels_do_not_consult_the_rule() -> None:
    """T36: no script, hook or workflow calls the rule (acceptance 4: no friction)."""
    channels = [rel for rel in _tracked("scripts", ".github", ".githooks", ".pre-commit-config.yaml") if rel.endswith(_CHANNEL_SUFFIXES)]
    assert any(rel.startswith(".github/workflows/") for rel in channels), "premise: CI is tracked and scanned"
    for rel in channels:
        text = (_REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        assert _GUARD not in text and "_names_constitution" not in text, rel
```

---

## Tests (map)

| T | What it pins | Writer |
|---|---|---|
| T1–T2 | Location ownership; the composer reads the file through the constant | — |
| T3–T7 | The form table (case, separators, `./`, `..`, empty and dot-only components, trailing dot and space, both stream forms, 8.3 file and directory, HFS-ignorable, Windows, POSIX and extended-length absolute, another worktree, drive-relative, UNC lexically) and the neighbours, through the rule, `builder_write_refusal` and `fix_loop_write_refusal` | rule, builder lexical, fix loop lexical |
| T8 | A non-exact `str` is refused by the rule, which runs none of its code, and by the builder boundary | rule, builder |
| T9–T12 | Hard link under the root; hard link to the running checkout's file; root still checked when the checkout's file is missing; directory link with the file missing | rule |
| T13–T16 | Failing closed: unexaminable constitution, unexaminable target, metaclass-safe naming, resolution failure | rule |
| T17 | No friction: no on-disk change; a direct write works | — |
| T18–T21 | Native build (four forms, hard link), the ship tier still modifiable, fix loop | `execute_approved_build` |
| T22 | Visiting session handler (and two approved controls) | `build_session_permission_handler` |
| T23–T28 | `write_file` (every in-tree form, absolute in-tree forms, neighbours, hard and directory link, effect-broker context), `edit_file` (every in-tree form, hard link, the ship tier) | SWE tools |
| T29–T31 | `FileWriterAgent` proposal and write; hard link under its working directory; the bundled notes path with a `..` filename | `FileWriterAgent`, `_mesh_write_file` |
| T32–T33 | `docx_create`, `pptx_create` (and a neighbour created); `docx_revise`, `xlsx_update` on hard links (and a neighbour revised) | office writers |
| T34–T36 | Census A (callers), census B (write sites), the Captain's channels | — |

Hard-link and directory-link tests skip where the host cannot make a link. The campaign host (win32 NTFS) can make both: a junction needs no privilege. A mutant whose only killer skipped counts as **not run**, not killed.

---

## Milestones (about 50 Builder tool calls each)

| M | Scope | Focused checks (run at `-n 0`; never `pytest tests/`) |
|---|---|---|
| **M1** | Sections 1, 2 and 7; write the whole of Section 8's file | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1344_constitution_write_refusal.py -v -n 0 -k "not write_file and not edit_file and not file_writer and not bundled and not office and not inventoried and not guarded_or_classified and not channels"`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf894_builder_write_boundary.py tests/test_bf898_fix_loop_grader_protection.py tests/test_builder_guardrails.py tests/test_bf896_session_permission_handler.py tests/test_bf896_executor_identity_and_blocks.py tests/test_bf904a_failed_build_restore.py tests/test_bf904a_unapplied_blocks.py tests/test_bf904a_git_hardening.py tests/test_bf897_build_pipeline_scale_and_checkout.py -q -n 0`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_standing_orders.py tests/test_ad893_standing_orders_api.py tests/test_bf910_standing_orders_lookup.py -q -n 0`; `d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check`. Cut: local commit `AD-1344 S1 M1: the constitution write rule and the builder boundary`. |
| **M2** | Sections 4, 5 and 6 | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1344_constitution_write_refusal.py -v -n 0 -k "write_file or edit_file or file_writer or bundled or office"`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad544_native_tools.py tests/test_ad1316_real_effect_routes.py tests/test_ad1316_governed_effect_broker.py tests/test_ad1179_tool_schema_golden.py tests/test_ad1179_schema_vocabulary_guards.py tests/test_file_writer.py tests/test_ad838_office_create_wiring.py tests/test_skill_framework.py tests/test_ad1284_consensus_gate_reachability.py tests/test_bf910_standing_orders_lookup.py -q -n 0`; a fresh-interpreter import check (no cycle): `d:/ProbOS/.venv/Scripts/python.exe -c "import probos.cognitive.builder_paths, probos.agents.file_writer, probos.skill_framework, probos.cognitive.swe_harness.tools, probos.runtime"`. Cut: local commit `AD-1344 S1 M2: SWE harness, FileWriterAgent and office writers call the rule`. |
| **M3** | Census tests green, the mutation campaign (below), the trackers (Section 9), the ledger, and the section audit (each Section maps to code, each T to a test) | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1344_constitution_write_refusal.py -v -n 0`; `d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check`; `d:/ProbOS/.venv/Scripts/python.exe scripts/check_seam_contracts.py`; `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1184_ad_ledger.py tests/test_ad1343_seam_registry.py -q -n 0`. Cut: local commit `AD-1344 S1 M3: inventory censuses and trackers`. |

**Census rule for the Builder (M3).** If census B reports a key that is not in `_WRITE_SITES`, add a row only when the path is fixed: constructor-injected, a temporary file, a fixed name or suffix that cannot be `federation.md`, or a store record. Cite `file:line` in your report. If the path comes from intent or tool parameters, **stop** and report to the orchestrator for the Architect. The broad gate is the main session's: one receipted run, after the Diff Reviewer.

---

## Mutation table (run once on the final tree; every anchor is a whole, unique, stripped line)

Apply one mutant at a time, run the named tests at `-n 0`, and restore. **Campaign of record:** record the base tree SHA and the sha256 of `builder_paths.py`, `standing_orders.py`, `swe_harness/tools.py`, `agents/file_writer.py`, `skill_framework.py`, `tests/test_ad1344_constitution_write_refusal.py` and `tests/test_bf894_builder_write_boundary.py`. When the orchestrator's dry run executes this table against these exact files, it is the campaign of record. A later Builder whose hashes match does not repeat it; if one file differs, rerun only that file's rows.

| ID | File | Line (stripped) → mutant | Killed by |
|---|---|---|---|
| B1 | builder_paths | `constitution = _constitution_lexical_refusal(path_str)  # AD-1344: ahead of the rules below, so its reason is given` → `constitution = None` | T22, T5[exact], T8 |
| B2 | builder_paths | `return constitution_write_refusal(path_str, work_dir)  # AD-1344: after the .git identity check` → `return None` | T19 |
| B3 | builder_paths | `return git_refusal` → `pass` | `tests/test_bf894_builder_write_boundary.py::test_identity_check_refuses_a_hard_link_to_the_git_pointer` |
| B4 | builder_paths | `unified = _DRIVE_PREFIX.sub("", path_text.replace("\\", "/"), count=1)` → `unified = path_text.replace("\\", "/")` | T5[drive-relative] |
| B5 | builder_paths | `collapsed = posixpath.normpath(unified)` → `collapsed = unified` | T5[dot-dot] |
| B6 | builder_paths | `names = [_canonical(part.split(":", 1)[0]) for part in collapsed.split("/")]` → `names = [_canonical(part) for part in collapsed.split("/")]` | T5[default-stream], T5[named-stream] |
| B7 | builder_paths | `names = [name for name in names if name]` → `names = names` | T5[dots-only-component] |
| B8 | builder_paths | `return len(tail) == len(_CONSTITUTION_PARTS) and all(` → `return all(` | T6[config/standing_orders] |
| B9 | builder_paths | `return name == expected or (_SHORT_NAME.search(name) is not None and name[:2] == expected[:2])` → `return name == expected` | T5[short-name-file], T5[short-name-directory] |
| B10 | builder_paths | `if type(path_text) is not str:` → `if False:` | T8 |
| B11 | builder_paths | `lexical = _constitution_lexical_refusal(path)` → `lexical = None` | T8 |
| B12 | builder_paths | `target = Path(root) / target` → `pass` | T9 |
| B13 | builder_paths | `if _names_constitution(str(resolved)):` → `if False:` | T12 |
| B14 | builder_paths | `candidates = [constitution_path()]` → `candidates = []` | T10 |
| B15 | builder_paths | `candidates.append(Path(root).joinpath(*_CONSTITUTION_RELATIVE_PARTS))` → `pass` | T9 |
| B16 | builder_paths | `continue  # no constitution there: nothing to alias` → `return None` | T11 |
| B17 | builder_paths | `return _constitution_unverifiable(path, "constitution", exc)` → `continue` | T13 |
| B18 | builder_paths | `return _constitution_unverifiable(path, "target", exc)` → `return None` | T14 |
| B19 | builder_paths | `if os.path.samestat(current, constitution):` → `if False:` | T9, T10, T19 |
| B20 | builder_paths | `return _constitution_unverifiable(path, "resolved", exc)` → `return None` | T16 |
| B21a | builder_paths | `return type(exc).__name__ if type(type(exc)) is type else "Exception"` → `return type(exc).__name__` | T15 |
| B21b | builder_paths | same line → `return "Exception"` | T13 |
| S1 | standing_orders | `CONSTITUTION_FILENAME = "federation.md"` → `CONSTITUTION_FILENAME = "federation2.md"` | T1 |
| S2 | standing_orders | `CONSTITUTION_RELATIVE_PATH = f"config/standing_orders/{CONSTITUTION_FILENAME}"` → `CONSTITUTION_RELATIVE_PATH = f"config/{CONSTITUTION_FILENAME}"` | T1 |
| S3 | standing_orders | `return standing_orders_dir() / CONSTITUTION_FILENAME` → `return Path("absent") / CONSTITUTION_FILENAME` | T1, T10 |
| S4 | standing_orders | `("federation", CONSTITUTION_FILENAME),` → `("federation", "absent.md"),` | T2 |
| S5 | standing_orders | `fed = _load_file(d / CONSTITUTION_FILENAME)` → `fed = ""` | T2 |
| W1 | tools.py | `refused = constitution_write_refusal(str(path), _PROJECT_ROOT)  # AD-1344: write_file` → `refused = None` | T23, T26 |
| W2 | tools.py | same line → `refused = constitution_write_refusal(str(path), None)` | T25 |
| W3 | tools.py | `refused = constitution_write_refusal(str(path), _PROJECT_ROOT)  # AD-1344: edit_file` → `refused = None` | T27 |
| W4 | tools.py | same line → `refused = constitution_write_refusal(str(path), None)` | T28 |
| W5 | file_writer | `refused = constitution_write_refusal(str(p), Path.cwd())  # AD-1344: the proposal` → `refused = None` | T29 |
| W6 | file_writer | `refused = constitution_write_refusal(str(p), Path.cwd())  # AD-1344: the write` → `refused = None` | T29, T31 |
| W7 | file_writer | same line → `refused = constitution_write_refusal(str(p), None)` | T30 |
| W8 | skill_framework | `refused = constitution_write_refusal(str(target), Path.cwd())  # AD-1344: docx_create` → `refused = None` | T32 |
| W9 | skill_framework | `refused = constitution_write_refusal(str(target), Path.cwd())  # AD-1344: pptx_create` → `refused = None` | T32 |
| W10 | skill_framework | `refused = constitution_write_refusal(str(source), Path.cwd())  # AD-1344: docx_revise` → `refused = None` | T33 |
| W11 | skill_framework | same line → `refused = constitution_write_refusal(str(source), None)` | T33 |
| W12 | skill_framework | `refused = constitution_write_refusal(str(source), Path.cwd())  # AD-1344: xlsx_update` → `refused = None` | T33 |
| H1 | builder.py | `path_error = builder_write_refusal(change["path"], work_dir)` → `path_error = None` | T18 |
| H2 | copilot_adapter | `if kind == "write" and builder_write_refusal(rel) is not None:` → `if False:` | T22 |
| H3 | builder.py | `fix_loop_write_refusal(change["path"], work_dir)` → `None` | T21 |

Equivalent mutants, excluded with reasons:
- `if root is not None and not target.is_absolute():` → `if root is not None:`. Joining an absolute path to a root yields the absolute path, so behaviour is the same.
- `return None  # not on disk, so not a second name of an existing file` → `continue`. The next candidate stats the same missing target and the loop ends in `return None`.

Wiring a campaign cannot reach by tests alone (verified by reading; the Diff Reviewer checks them):
- `runtime.submit_write_with_consensus` (`runtime.py:4767`) and `_gated_commit_write` (`:5228-5241`) reach the guarded `commit_write`. No test boots a runtime for this.
- The office agents exist only when `office_skills.enabled` (default `False`, `config.py:3736`). The tests construct them directly.
- The Copilot SDK registration of the permission handler (the SDK is optional). T22 calls the factory's handler.

---

## Section 9: Trackers

### `PROGRESS.md`

SEARCH:
```markdown
# ProbOS Progress

```
REPLACE:
```markdown
# ProbOS Progress

**AD-1344 S1 (2026-10-21), #1596 -- agents cannot amend the Federation Constitution; the Captain amends it through ordinary development, as before.** One rule, `builder_paths.constitution_write_refusal`, refuses a write to `config/standing_orders/federation.md` with a one-line reason naming AD-1344. It matches the path as written (case, separators, `./`, `..`, stream suffixes, 8.3 short forms, a leading drive, in any tree), once resolved (a linked directory), and by `os.stat` identity with the constitution under the writer's root or in the running checkout (a hard link). A value that is not an exact `str`, and a path it cannot examine, are refused too. The callers: the builder boundary (the native build, the test-fix loop and, lexically, the visiting session's permission handler), the SWE-harness `write_file` and `edit_file`, `FileWriterAgent` (the proposal, and the write that the bundled todo, notes and reminder agents call directly) and the office writers `docx_create`, `docx_revise`, `pptx_create` and `xlsx_update`. `standing_orders.py` owns the location (`CONSTITUTION_FILENAME`, `CONSTITUTION_RELATIVE_PATH`, `constitution_path()`). Two AST censuses in `tests/test_ad1344_constitution_write_refusal.py` pin the callers and classify the file writes in the agent-facing modules. Shell and code-execution paths (`run_command`, `run_python`) are outside this slice (#1596, acceptance 5). The ship, department and agent tiers and the other `config/` files keep their outcome. Slice 2 (a formal amendment process) stays paused; #1596 stays open.

```

### `DECISIONS.md` (insert before the heading that follows the newest entry of the recent run; on `e237c352` that run ends with BF-910 at `:422`)

SEARCH:
```markdown
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
### AD-1344 S1 -- Agents cannot amend the Federation Constitution: one write rule, called by the agent-reachable writers (2026-10-21, #1596)

- *Scope.* Slice 1 of #1596 only; Slice 2 stays under the new-capability pause and #1596 stays open. Contract: `prompts/ad-1344-s1-constitution-write-refusal.md` (first drafted 2026-10-19 on `45058ae7`, redrafted 2026-10-21 on `e237c352`).
- *D1/D2 (home and owner).* The rule is `builder_paths.constitution_write_refusal`, in a module already listed in `FIX_LOOP_PROTECTED_PATHS`. `standing_orders.py` owns the location, beside BF-910's `standing_orders_dir()`.
- *D3/D14 (what is refused).* The cases are: a value that is not an exact `str` (nothing of it is read); the path as written, judged on its last three components in BF-894's canonical form after separators, a leading drive and `..` are normalised and stream suffixes dropped, with an 8.3 form accepted, in any tree; the resolved path, judged the same way; an existing file with the constitution's `os.stat` identity under the writer's root or in the running checkout; an `os.stat` that raises `OSError` or `ValueError` other than not-found; and a resolution that raises `OSError`, `RuntimeError` or `ValueError`. Exception class names are read through `type` only when the metaclass is exactly `type`.
- *D4.* In `builder_write_refusal` the lexical constitution check follows the empty-path check, so its reason is the one given. The full rule follows the `.git` identity check, which keeps its reasons and its NUL behaviour.
- *D5.* The office writers call the rule too, because they save to a path an intent supplies; the issue's list did not name them.
- *D9.* Each writer refuses in its existing error shape. In the SWE tools the call is the first statement of the `try` that already held `str(path)`.
- *Rejected.* A new `security/constitution.py` (a new protected path and self-test row for no gain); `security/file_access.py` (read-side and runtime-coupled); a lexical-only rule (misses hard links); a file lock or mode change (friction for the Captain); a census of intent and tool names (every later intent would edit it).
- *Residuals (numbered on #1523 by the orchestrator).* Shell and code execution (acceptance 5); MCP servers and agent-designed code; the writer call sites are outside `FIX_LOOP_PROTECTED_PATHS` (tests pin them); check-then-write is not atomic outside the Windows strict-native handle path; the census bounds; BF-908's read floor has no write-side sibling, so `config/system.yaml` stays writable through `write_file`; over-refusal by design of copies in other trees and of 8.3-shaped names.
- *Reversal.* Revert the AD-1344 S1 commits. Nothing persisted changes.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

The orchestrator appends the *Mutation campaign of record* bullet (tree, row results, sha256 of the files above) to this entry after the campaign runs, as BF-910 did. AD-1346 M3a has merged (PR #1612, `7171aded`): its entry, `### AD-1346 M3a -- the inert shadow AdmissionService library`, is the newest of the run and precedes the same heading, so this entry is inserted between M3a's and that heading (the anchor line occurs once on `7171aded`).

### Ledger

After both edits: `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (write mode), which regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`. Both files belong to the M3 commit. Then run `--check`; the gate's `ad-ledger` phase fails without it.

### Not updated

`docs/development/roadmap.md`: no row (D12). `config/`, `.github/`, `scripts/`: untouched.

### GitHub (orchestrator)

- #1523: residuals R1–R7 below, each given its F-number.
- #1596: a comment that S1 is delivered, naming the residual of acceptance 5, and saying the issue stays OPEN.
- R6 (the BF-908 write-side gap): recommend a duplicate search, then a BF issue of its own. It is not part of S1.

---

## Deterministic gate checks (resolved up front)

| Check | Touched? |
|---|---|
| srp-size | No class gains a method. `DocxAgent`, `PptxAgent`, `XlsxAgent`, `WriteFileTool`, `EditFileTool` and `FileWriterAgent` grow by 4–5 lines each, far under 500. The baselined classes `CopilotBuilderAdapter` (`architecture-baseline.yaml:417`) and `AgentSkillService` (`:897`) are untouched. `builder_paths` has no class. |
| layer-import | No new row. `cognitive → cognitive` is the same rank (`architecture-baseline.yaml:12-17`). `agents` and `skill_framework` are unranked (`check_architecture_principles.py:80-85`). |
| db-connect / unowned-task | None added. |
| config reference / profiles / facade | No config field. `config/system.yaml` untouched. |
| store registry | No store or table. `store-baseline.yaml:154` (`skill_framework`) is unchanged. |
| seam contracts | `docs/development/seams/p0-manifest.yaml` names none of these modules. The AD-1343 registry is unaffected (D16). |
| AD ledger | `PROGRESS.md` and `DECISIONS.md` change, so regenerate (Section 9). `tests/test_ad1184_ad_ledger.py` runs `--check`. |
| AD-1195 event freeze | No `EventType` added. |
| AD-1179 schema golden and vocabulary guards | No schema or `params.get` key added to any tool `invoke`. |
| Hidden pins | BF-898 NUL premise (`test_bf898…:250-255`): kept by D4. BF-898 self-test coverage (`:150-159`): untouched (no protected path added). BF-894 `_LEGIT` (`:30`, asserted `:42`): gains two rows. BF-894 patched-`os.stat` test (`:122-136`) and hard-link test (`:105-113`): `.git` still answers first. `test_builder_guardrails.py:36` (`config/system.yaml` allowed): unchanged. `test_ad1284…:412-429` (`path=123` stays noisy): `Path(123)` still raises before the new call. `test_ad544…:127-131` (12 tools): unchanged. |

---

## Diff Reviewer: properties to verify (gpt-6.1-sol)

1. In each function of `_EXPECTED_CALLERS`, the call to `constitution_write_refusal` comes before every operation on that path that creates, opens for writing, truncates, saves or links a file (`mkdir`, `write_text`, `save`, the strict-native open).
2. Each refusal string contains `AD-1344` and no line break. It formats exact `str` values: the path through `repr`, and an exception class name that is an identifier, else the literal `Exception` (A1 D22, T39). The non-`str` reason formats nothing.
3. `constitution_write_refusal` returns non-None in exactly these cases: a non-exact-`str` value; a lexical match; a resolved-name match; `samestat` with either candidate; `OSError`/`ValueError` (other than `FileNotFoundError`/`NotADirectoryError`) from `os.stat` of a candidate or the target; `OSError`/`RuntimeError`/`ValueError` from `resolve`. Every other exception propagates.
4. `_exception_name` reads no attribute of an exception class whose metaclass is not exactly `type`.
5. For an exact-`str` path that does not end in the constitution's components and is not an identity alias, `builder_write_refusal` returns what it returns on `e237c352`. The BF-894, BF-898 and BF-904a suites pass with only `_LEGIT` changed.
6. The `.git` identity check runs before the constitution identity check.
7. Caller-code operations against the base. For each writer, list every operation on a caller-controlled value (`if not path`, `str(path)`, `Path(path)`, `str(p)`, `os.path.expanduser(...)`) and whether it sits inside or outside a `try`, in the base and in the change. The change adds no such operation outside a `try` that held it on the base, and no handler is changed.
8. `CONSTITUTION_FILENAME`, `CONSTITUTION_RELATIVE_PATH` and `constitution_path()` are defined in `standing_orders.py`, and `builder_paths.py` takes the location from them. (Read-side, as on the base: `experience/commands/commands_directives.py:20-22` reads `_DEFAULT_ORDERS_DIR` and `:48` compares the literal `"federation.md"`; recorded on #1523.)
9. No change under `.github/`, `scripts/`, hooks or `config/`; no chmod or lock; no new config field.
10. The census tables match the tree, and each `guarded` row's function contains a guard call. Spot-check two fixed-path reasons against the code.
11. No import cycle, and no new layer-import, srp-size, db-connect or unowned-task row.
12. Writer-level tests write only under `tmp_path`, and no test resolves the UNC form.
13. Tracker and docstring text makes no claim about when a state holds, and uses no universal word that is not pinned by a named test or enumeration.

---

## What This Does NOT Change

- `ship.md`, the department and agent tiers, `DirectiveStore`.
- Hooks, CI, branch protection, the Captain's editing and git.
- `FIX_LOOP_PROTECTED_PATHS` and `FIX_LOOP_SELF_TEST`.
- Shell (`run_command`), `run_python`, `install_package`, MCP servers, agent-designed code.
- The HXI config router and the Captain's skill commands.
- The effect broker and its adapters.
- Other `config/` files, including `config/system.yaml` (R6).
- Slice 2: the amendment record, versioning, propagation and the PR label.

## Interplay

- **AD-1343** (merged): no stop check was added inside `write_file`/`edit_file` (the `tools.py` diff `45058ae7..e237c352` carries BF-910 hunks only). The stop seam is `ToolRegistry.check_and_invoke` (`SEAM_TOOL`), so the order is: stop check → `invoke` → parameter checks → constitution check → write. No registry or census entry is needed (D16).
- **AD-1346 M3a** (merged as PR #1612, `7171aded`): touches the admission package, `runtime.py`, `shutdown.py` and the trackers. The only overlap with this contract is the `DECISIONS.md` and `PROGRESS.md` anchors, re-checked on `7171aded` (Section 9). The `PROGRESS.md` anchor is the first line and the blank line after it, so it applies on any later top entry.
- Nothing else in flight is coordinated.

## Residuals (for #1523; the orchestrator numbers them)

- **R1** Shell and code execution (`run_command`, `run_python`, `install_package`) can still write the constitution. The sandbox and AD-1328 policy govern them (acceptance 5).
- **R2** Out-of-process and executed-code writers are not path-gated: MCP servers (`mcp_invoke`, workbench tools) and agent-designed code (AD-886).
- **R3** The writer call sites and `standing_orders.py` are outside `FIX_LOOP_PROTECTED_PATHS`. Tests the fix loop cannot write pin them: census A and T1's literal.
- **R4** The check and the write are separate steps. A link swapped in between is caught only on the Windows strict-native handle path (`_locked_native_target` refuses reparse points and multi-link targets, `tools.py:186-217`).
- **R5** The census bounds: `.write(`, `Path.replace`, `os.open`/`os.fdopen`, names imported bare (`from shutil import rmtree`), dynamic dispatch, and modules outside `_CENSUS_SCOPE`.
- **R6** BF-908's config floor is read-side only. `write_file`, `edit_file` and the builder can write `config/system.yaml`, which may hold `auth.crew_scope_token`. Recommend its own BF.
- **R7** Over-refusal by design: any path ending in `config/standing_orders/federation.md` in any tree, and 8.3-shaped names that share the first two characters.

## Acceptance Criteria

1. Each writer in `_EXPECTED_CALLERS`, and the native build, fix loop and visiting session through `builder_write_refusal`, refuses the constitution in each form its test drives, with a reason naming AD-1344 (T5–T7, T18–T33). A hard link is refused through each writer whose test makes one; a directory link is refused through the rule and `write_file`.
2. The neighbours are still writable through the same writers (T4, T6, T20, T22, T24, T28, T29, T31–T33; BF-894 `_LEGIT`).
3. Both censuses and the channels scan pass (T34–T36).
4. The campaign of record kills every row of the mutation table (56 rows with Amendment A1).
5. One receipted broad gate and CI are green.
6. No friction: T17 and T36 pass, and the diff touches no hook, CI or `config/` file.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Prior Art and Blind Spots

Date used for the overdue check: **2026-10-21**. Interval for coding-agent harnesses: 90 days.

| Source | Decision |
|---|---|
| BF-894 canonical form (git `is_ntfs_dotgit`/`is_hfs_dotgit`, `builder_paths.py:16-25`) | **Reuse** `_canonical` and `_SHORT_NAME`. |
| BF-898 / DGM and HyperAgents absorptions (`hyperagents-absorption.md:31`) | **Absorb**: the constitution joins what the improver cannot reach. |
| BF-910 lessons (D20–D24, `DECISIONS.md:427-431`) | **Absorb**: the exact-`str` gate (D14), the `try` placement (D9), metaclass-safe naming. |
| AD-481f sealed core (warn-only, opt-in, module paths) | **Reject** as the home: S1 must be unconditional. |
| BF-758/BF-908 read floor (`security/file_access.py:190-228`) | **Reject** as the home (read-side). Its missing write side becomes R6. |
| Claude Code CVE-2025-59829 / CVE-2026-25724 (deny rules bypassed through symlinks) | **Absorb**: resolve, then compare disk identity. |
| Cursor (re-examined, overdue since 2026-06-13). Forum and third-party reports: approval-gated dotfile and config protection; agents bypass it through the shell; a copy-edit-move workaround; CVE-2026-26268 (writing `.git` configuration) | **Absorb**: refuse at the tool level, and keep the shell as a named residual (R1). The copy-edit-move route needs a move or rename by a caller-chosen path, and census B finds none in the agent writers. CVE-2026-26268 is BF-894's class, already covered. |
| SWE-agent (re-examined, overdue since 2026-03-20). The tools config page shows no protected-path, deny-list or edit-filter option; isolation is container-scoped | Nothing new. |
| praisonai protected paths (tool-level refusal) | The same shape; nothing new. |

**Reference-projects row updates** (for the orchestrator's next docs change):
- SWE-agent → `2026-10-21 | checked | AD-1344 S1 (#1596) Prior Art, prompts/ad-1344-s1-constitution-write-refusal.md (tools config: no protected-path option; nothing new)`
- Cursor → `2026-10-21 | checked | AD-1344 S1 (#1596) Prior Art (forum and third-party reports: approval-gated protected files, shell bypass, copy-edit-move workaround; CVE-2026-26268 .git config write)`
- Considered, deferred: OpenCode (overdue since 2026-05-08; not relevant to write boundaries).

**Blind spots:**
1. TOCTOU between the check and the write (R4).
2. Over-refusal of copies and of 8.3-shaped names (R7).
3. Inventory decay, handled by the censuses (R5 states their bounds).
4. Deleting or moving the constitution. Census B finds no agent writer that deletes, moves or renames by a caller-chosen path: each `unlink`, `rmdir`, `rename`, `replace` and `rmtree` row is classified with a fixed path.
5. A case variant is refused on case-sensitive filesystems too, the same policy as BF-894.
6. A lower tier "overriding" the constitution through `DirectiveStore` is out of scope (Do Not Build).
7. A drive-relative path, a bypass in my own 2026-10-19 draft, is now refused (D3).

---

## Verified Against Codebase (2026-10-21, on `e237c352`)

```
git diff 45058ae7 HEAD --stat -- <paths>  -> changed: standing_orders.py (+31), swe_harness/tools.py (+93/-), copilot_adapter.py (+82/-), runtime.py (+26),
                                             security/file_access.py, security/crew_scope.py (new), tools/registry.py, tools/delegate_task_tool.py, tools/browser/credentials.py (message only)
                                           unchanged: builder_paths.py, builder.py, agents/file_writer.py, skill_framework.py, tests/test_bf894*, tests/test_bf898*
builder_paths.py:27-38 docstring tail + imports; :41-47 ALLOWED_PATH_PREFIXES ("config/" :44); :50-55 FORBIDDEN_PATHS; :60 _SHORT_NAME; :66-68 _canonical
builder_paths.py:71 def builder_write_refusal; :78-81 normalized/empty/".."; :83 absolute refused; :110-112 work_dir None / _git_identity_refusal
builder_paths.py:115-134 _git_identity_refusal (OSError only; ValueError propagates); :145-156 FIX_LOOP_PROTECTED_PATHS (:147 builder_paths.py); :182 fix_loop_write_refusal; :201; :207
builder.py:25,27 imports; :99 _validate_file_path = builder_write_refusal; :1747 _restore_pre_build_files (:1760 write_bytes, :1768 unlink, :1777 rmdir)
builder.py:3121 async def execute_approved_build (last top-level def; nested defs in file: none after :2900); :3252 path_error = builder_write_refusal(change["path"], work_dir)
builder.py:3319-3331 replacements search/replace; :3339,:3362,:3544,:3551 write_text; :3496 fix_loop_write_refusal(change["path"], work_dir); :2772-2775 _validate_python skips non-.py
copilot_adapter.py:25 import builder_write_refusal; :231-235 _PERMISSION_APPROVED/_DENIED/_PATH_FIELDS; :269-293 _session_relative (exact str rel); :322 builder_write_refusal(rel); :327 build_session_permission_handler; :360,:386 seed_session_directory write_text
standing_orders.py:7 "immutable across all instances"; :35 _DEFAULT_ORDERS_DIR; :103-105 standing_orders_dir; :140-141 lru_cache _load_file; :153 get_order_tiers; :174-176 specs ("federation","federation.md"); :434 compose_instructions; :475-477 fed = _load_file(d / "federation.md")
crew_profile.py:13-25 stdlib imports only (AgentRegistry under TYPE_CHECKING) -> no cycle via builder_paths
swe_harness/tools.py:21 from typing import Any, TYPE_CHECKING; :23-27 standing_orders import; :72 logger; :75 _PROJECT_ROOT; :186-217 strict lock refuses reparse/multi-link; :241-244 _resolve_path
swe_harness/tools.py:969 WriteFileTool; :992-994 resolve_effect_target; :1002 refuse_undeclared_params; :1007-1012 path/content checks, try, _resolve_path(str(path)); :1035-1045 handler (re-raise under effect ctx)
swe_harness/tools.py:1048 EditFileTool; :1089-1096 checks, replace_all, mutation_started, try; :1150-1161 handlers; tool_ids: 12 (read_file .. run_command)
effect_adapters.py:75-152 _NativeFileEffectAdapter.prepare (resolves only); executor.py:869-871 _strict_native_target/_root into context
agents/file_writer.py:9-10 imports; :12 logger; :36 IntentDescriptor write_file propose_commit; :107-127 act try; :136-148 commit_write
runtime.py:4738 submit_write_with_consensus; :4767 commit_write(path, content); :5224 "write_file": self._gated_commit_write; :5228-5241 uncoerced params
organizer_agents.py:56-66 _mesh_write_file -> commit_write; :187-191 model-chosen filename; :348-349 reminders; productivity_agents.py:116-125, :188-189
skill_framework.py:19-21 aiosqlite / protocols imports; :26 logger; :71 DocxAgent; :98 handle_intent (no try); :113-136 docx_create; :137-149 docx_revise; :206-210 create_docx save
skill_framework.py:251-260 revise_docx; :306-329 pptx_create; :397-401 create_pptx save; :478-487 xlsx_update; :511-528 update_xlsx
config.py:3733-3736 OfficeSkillsConfig.enabled: bool = False
skill_forge.py:165-262 forge (rmtree :262 in finally); :299-317 _write_files (containment :305-315); skill_catalog.py:226 class; :647-686 import_skill (copytree :678); :784/:814 _rewrite_frontmatter; :816/:843 remove_skill
census B scope grep (write_text|write_bytes|unlink|rename|touch|rmdir|save|os.*|shutil.*|open): every hit maps to a _WRITE_SITES row; code_runner.py:526 and code_execution_tool.py:439 are inside strings
tools/browser/credentials.py:184-189 _save (open "w", os.replace); :236-251 materialize_to_temp (os.unlink :250); recording_reaper.py:89 _reap_sync (:120,:153 unlink; :172 rmdir)
code_execution_tool.py:621 _start_fetch_broker (:652); :675 invoke (:1027 rmtree); :1136 _stage_thread_artifacts (:1175); actions.py:998 _action_upload_file (:1044 _os.unlink); avatar_agents.py:101 act (:170 os.replace); http_fetch.py:906 (:913 .save)
records_store.py:1202-1210 _safe_path containment; knowledge/store.py:1408-1421 .json-suffixed artifact paths
security/file_access.py:190-228 protected_read_roots / protected_config_files (read floor); :593-653 PinnedDirectory write helpers, called only from execution/workspace_result_store.py (fixed names)
tests/test_bf894_builder_write_boundary.py:30 _LEGIT; :42; :105-113; :116-119; :122-136; :139-147 _no_real_git; :161-170
tests/test_bf898_fix_loop_grader_protection.py:150-159; :250-260 NUL premise
tests/test_builder_guardrails.py:36; tests/test_ad544_native_tools.py:127-131 (12 tools); tests/test_ad838_office_create_wiring.py:10-14 (docx/openpyxl/pptx imported at top); tests/test_ad1284_consensus_gate_reachability.py:412-429
tests/test_file_writer.py:12,26 FileWriterAgent(pool="filesystem"), await agent.start()
tools/protocol.py:81-91 ToolResult (success = error is None)
architecture-baseline.yaml:12-17 layers; :417 CopilotBuilderAdapter; :897 AgentSkillService; check_architecture_principles.py:80-85, :187-188 (500 lines / 15 methods)
DECISIONS.md:422 BF-910 (newest of the run); :436 "### Explicit delegation models, plain-id profile models ..." (unique); PROGRESS.md:1 "# ProbOS Progress" (unique)
federation.md:1-4 precedence; crew-personnel-management.md:331 "immutable by design"; hyperagents-absorption.md:31; git log -- config/standing_orders/federation.md -> 19 commits
scripts/ad_ceiling.py -> CEILING AD-1346, NEXT AD-1347
```

## Absence Verified (2026-10-21)

| Claim | Run | Found | Holds |
|---|---|---|---|
| No `apply_patch`-style tool | Grep `apply_patch\|"apply"\|patch_file\|def apply_diff\|git apply` in `src/probos` | `crew_orchestrator.py:2829` `("apply", "inspect")` only (unrelated) | yes |
| No tool added since the draft | Grep `tool_id: str = "` in `src/probos` | 12 in `swe_harness/tools.py` (`:411`…`:1172`) plus non-tool dataclass fields | yes |
| No write intent other than the known ones | Grep `IntentDescriptor\(\s*name="…(write\|save\|edit\|delete\|…)"` plus office names | `file_writer.py:36`; office `skill_framework.py:85,91,284,454` | yes |
| BF-908's floor has no write-side caller | Grep `protected_config_files\|protected_read_roots\(` | `code_search.py:337`, `copilot_adapter.py:110`, `file_access.py:199,265`, `repository_instructions.py:62`, `tools.py:334,908`, all reads | yes |
| No new write primitive in the files changed since `45058ae7` | Grep the write-primitive pattern across `src/probos` (69 files), triaged by changed file | `credential_store.py:202-203`, `identity_key_store.py:237`, `proactive.py:539`, `routers/agents.py:939-940`, `startup/shutdown.py:936`: fixed store, state or session paths, or the Captain's route; `agent_stop.py`, `crew_*`: none | yes |
| AD-1343 added no check inside `write_file`/`edit_file` | `git diff 45058ae7 HEAD -- swe_harness/tools.py` | BF-910 hunks only (`:23-27`, `:808-923`) | yes |
| No seam registry or manifest entry names these modules | Grep `builder_paths\|swe_harness\|file_writer\|skill_framework\|standing_orders\|copilot_adapter\|write_file\|edit_file` in `tests/fixtures/ad1343_seam_registry.py` and `docs/development/seams/p0-manifest.yaml` | none | yes |
| No test writes the repository's constitution through a writer | Grep `federation\.md` in `tests/` | direct `write_text` into `tmp_path`, plus reads | yes |
| No roadmap row for AD-134x | Grep `AD-134[0-9]` in `roadmap.md` | 0 | yes |
| No AD-1344 code exists yet | Grep `AD-1344` in the worktree | `prompts/bf-906-…`, `docs/architecture/architecture-review-2026-10-20.md` (numbering notes), the draft file | yes |
| No git hooks or pre-commit config tracked | `git ls-files .githooks .pre-commit-config.yaml .github/workflows` | `ci.yml`, `docs.yml` | yes |
| No nested function holds a census write site | Grep `^\s{8,}(async )?def ` in `builder.py`, `copilot_adapter.py`, `code_execution_tool.py`, `tools/browser/*`, `skill_forge.py`, `skill_catalog.py` | `_fetch` (`code_execution_tool.py:646`) ends before `:652`; credentials `_do` closures start after `:189` and `:250`; others away from the sites | yes |

---

## Orchestrator pre-build verification and corrections (2026-10-21, on `7171aded`)

Run on scratch worktrees before any Builder, as for AD-1346 M3a. The evidence files are outside the repository.

| Check | Result |
|---|---|
| Every SEARCH against `7171aded` (`check_search_replace_blocks.py`) | 20 pairs; each SEARCH occurs exactly once |
| The whole contract applied (20 pairs and the new file), AD ledger regenerated | applied; `gen_ad_ledger.py --check` reports current |
| `tests/test_ad1344_constitution_write_refusal.py`, `-n 0` | 144 passed, no skip (this host can make hard links and junctions) |
| Focused check: 112 test files (the new file, the BF-894 table and every test file that names a changed module), scrubbed environment, `-n 8` | 4,550 passed, 33 skipped, 0 failed; the skips are symlink privilege, POSIX-only and an uninstalled SDK, none in the new file or the BF-894 table |
| The new file and the BF-894 table, unscrubbed, `-n 0` | 210 passed |
| `check_architecture_principles.py --check`, `check_seam_contracts.py`, a fresh-interpreter import of the five changed modules and `probos.runtime` | pass |
| The mutation table, 42 rows, on the corrected tree | 42 killed by a named test (11, 14 and 17 rows in three worktrees) |
| The two mutants the contract calls equivalent | both survive (210 passed), as the contract argues |
| Platform | every check above ran on Windows, Python 3.12.13; CI runs `ubuntu-latest`, Python 3.12, and is the first Linux run. The OS-dependent code in the new file is `_dir_link` (a junction on Windows, a symlink elsewhere) and `_hard_link`; both skip when the host cannot make the link |

**Corrections applied before the build**

1. The `Base` line, the `Interplay` bullet and the `DECISIONS.md` note say that AD-1346 M3a has merged (PR #1612). Its entry is the newest of the recent run and precedes the same anchor, so this entry goes after it.
2. **The autouse guard names the repository's constitution by a literal path.** First run of the table: 40 rows killed, S1 and S3 INVALID. S1 (`CONSTITUTION_FILENAME = "federation2.md"`) and S3 (`constitution_path()` returns a path that does not exist) made the guard's `real.read_bytes()` raise in every test's setup, so the first test ended in an error and T1's assertions never ran: detected, but not killed by the named test, and acceptance 4 asks for kills. With `_REAL_CONSTITUTION = _REPO_ROOT / "config" / "standing_orders" / "federation.md"`, S1, S2 and S3 fail T1 and S4 and S5 fail T2. The guard now watches the file itself, not whatever `constitution_path()` returns. Rerun of the whole table: 42 of 42.

---

## Amendment A1 (2026-10-21, round-1 review F1 to F4; `claude-architect`)

Applies to candidate r1 (`80c6eaae`). It supersedes Section 2's `_exception_name` and the `builder_write_refusal` docstring, and Section 4's 4b and 4c blocks. With A1 the file has 39 test functions, and the mutation table has 56 rows.

### Decisions

| # | Decision | Rejected alternatives |
|---|---|---|
| D20 | (F1) The refusal log line of `write_file`/`edit_file` is a constant: `AD-1344 <Tool> refused operation=<op> reason_code=constitution_refused`. It is the same with and without `_effect_dispatch_context`, and it formats nothing. The returned error is unchanged. An exception from logging filters or handlers outside `Handler.handleError` enters the existing handlers of the same `try`; in `edit_file` the `except FileNotFoundError` arm comes before `except Exception`, so a `FileNotFoundError` raised there is reported as a missing file (round-2 note R2-1). (T37) | Keeping the refusal text outside the strict context: a branch, and the raw path reaches a shared log. No log line: loses the reason code under the broker, which stores only a digest (`effect_broker.py:920-930`), and loses the only log record outside it. |
| D21 | (F2) The first statement of each tool's existing `try` is `path_text = str(path)`. The rule, `_resolve_path` and the returned path use `path_text`. Handlers unchanged. (T38) | Converting before the `try`: it moves `str(path)` outside the `try` that held it (BF-910 F1/F3). Accepting `os.PathLike`: `__fspath__` runs caller code. |
| D22 | (F4) `_exception_name` returns the class name read through `type`'s descriptor when the metaclass is exactly `type` and the name is an exact-`str` identifier, else `Exception`. (T39) | Narrowing the "one-line" and "formats only exact `str`" claims in five places instead: adds conditions to the prose. Importing `swe_harness.tools._exception_kind`: an import cycle, and that helper accepts a name with a line break (follow-up). |
| D23 | (F3) No code change. The claims that `builder_write_refusal` runs none of the value's code are narrowed to the rule. Recorded on #1523. | Moving the lexical check above `builder_paths.py:200`: changes the builder's result for a value that is not a `str` (`None` raises there on the base and on r1), outside S1, for an injected-only reach. |
| D24 | Prose: property 8 and T36's docstring are narrowed to what they check (review items (a) and (b)). | — |

### Tests

| T | What it pins | Writer |
|---|---|---|
| T37 | The refusal log line holds no caller path, with and without the strict effect context, and carries `operation=… reason_code=constitution_refused`. The returned error still names the path. | SWE tools |
| T38 | A path whose `__str__` gives the neighbour first and then the constitution: `__str__` runs once, the neighbour is written and edited, the constitution is unchanged, the returned path is the neighbour. | SWE tools |
| T39 | An exception class whose name has a line break, or is held as a `str` subclass, is reported as `Exception`; the reason has no line break, and none of the name's code runs. | rule |

### A1-W1 `src/probos/cognitive/swe_harness/tools.py` (WriteFileTool)

SEARCH:
```python
        try:
            refused = constitution_write_refusal(str(path), _PROJECT_ROOT)  # AD-1344: write_file
            if refused is not None:
                logger.warning("AD-1344 WriteFileTool refused: %s", refused)
                return ToolResult(error=refused)
            target = _resolve_path(str(path))
```
REPLACE:
```python
        try:
            path_text = str(path)  # AD-1344: write_file, the one conversion
            refused = constitution_write_refusal(path_text, _PROJECT_ROOT)  # AD-1344: write_file
            if refused is not None:
                logger.warning("AD-1344 WriteFileTool refused operation=write_file reason_code=constitution_refused")
                return ToolResult(error=refused)
            target = _resolve_path(path_text)  # AD-1344: write_file, the text the rule judged
```

### A1-W2 `tools.py`

SEARCH:
```python
            return ToolResult(
                output={"path": str(path), "bytes_written": len(str(content))}
            )
```
REPLACE:
```python
            return ToolResult(
                output={"path": path_text, "bytes_written": len(str(content))}
            )
```

### A1-W3 `tools.py` (EditFileTool)

SEARCH:
```python
        try:
            refused = constitution_write_refusal(str(path), _PROJECT_ROOT)  # AD-1344: edit_file
            if refused is not None:
                logger.warning("AD-1344 EditFileTool refused: %s", refused)
                return ToolResult(error=refused)
            target = _resolve_path(str(path))
```
REPLACE:
```python
        try:
            path_text = str(path)  # AD-1344: edit_file, the one conversion
            refused = constitution_write_refusal(path_text, _PROJECT_ROOT)  # AD-1344: edit_file
            if refused is not None:
                logger.warning("AD-1344 EditFileTool refused operation=edit_file reason_code=constitution_refused")
                return ToolResult(error=refused)
            target = _resolve_path(path_text)  # AD-1344: edit_file, the text the rule judged
```

### A1-W4 `tools.py`

SEARCH:
```python
            return ToolResult(output={"replacements": count, "path": str(path)})
```
REPLACE:
```python
            return ToolResult(output={"replacements": count, "path": path_text})
```

### A1-B1 `src/probos/cognitive/builder_paths.py`

SEARCH:
```python
def _exception_name(exc: BaseException) -> str:
    """The class name of *exc* through ``type``'s own descriptor; ``Exception`` under another metaclass."""
    return type(exc).__name__ if type(type(exc)) is type else "Exception"
```
REPLACE:
```python
def _exception_name(exc: BaseException) -> str:
    """The class name of *exc*, read through ``type``'s own descriptor, if it is an exact-``str`` identifier.

    ``Exception`` under another metaclass (nothing of the class is read) or for any other name.
    """
    cls = type(exc)
    if type(cls) is not type:
        return "Exception"
    name = cls.__name__
    return name if type(name) is str and name.isidentifier() else "Exception"
```

### A1-B2 `builder_paths.py`

SEARCH:
```python
    AD-1344: after the empty-path check, a value that is not an exact ``str`` or that names
    the Federation Constitution is refused with that rule's reason; with *work_dir*,
    ``constitution_write_refusal`` runs after the ``.git`` identity check.
```
REPLACE:
```python
    AD-1344: after the empty-path check, ``_constitution_lexical_refusal`` judges *path_str*
    and its reason, if any, is returned; with *work_dir*, ``constitution_write_refusal``
    runs after the ``.git`` identity check.
```

### A1-T1 `tests/test_ad1344_constitution_write_refusal.py` (T8)

SEARCH:
```python
def test_a_value_that_is_not_an_exact_str_is_refused_without_running_its_code(vessel: Path) -> None:
    """T8."""
```
REPLACE:
```python
def test_a_value_that_is_not_an_exact_str_is_refused_and_the_rule_runs_none_of_its_code(vessel: Path) -> None:
    """T8: the rule runs none of the value's code; ``builder_write_refusal`` refuses it."""
```

### A1-T2 test file (T39, after T15)

SEARCH:
```python
    assert refusal is not None and "(target: Exception)" in refusal
    assert ran == [], "the metaclass's __name__ ran"
```
REPLACE:
```python
    assert refusal is not None and "(target: Exception)" in refusal
    assert ran == [], "the metaclass's __name__ ran"


def test_a_failure_whose_class_name_is_not_an_exact_identifier_is_named_exception(
    vessel: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T39 (A1, F4): a class name with a line break, or held as a ``str`` subclass, is reported as ``Exception``."""
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
    (vessel / "docs" / "other.md").write_text("x", encoding="utf-8")
    real_stat = os.stat
    for cls in (TwoLines, Formatted):

        def _stat(path, *args, _cls=cls, **kwargs):  # type: ignore[no-untyped-def]
            if Path(path).name == "other.md":
                raise _cls(13, "denied")
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(builder_paths.os, "stat", _stat)
        refusal = constitution_write_refusal("docs/other.md", vessel)
        monkeypatch.undo()
        assert refusal is not None and "(target: Exception)" in refusal and "\n" not in refusal, cls
    assert ran == [], "the class name's own code ran"
```

### A1-T3 test file (T37, T38, after T28)

SEARCH:
```python
    result = await tool.invoke({"path": "docs/alias.md", "old_text": "CONSTITUTION v1", "new_text": "AMENDED"})
    assert not result.success and _AD in (result.error or "")
    assert _unchanged(swe_root)
```
REPLACE:
```python
    result = await tool.invoke({"path": "docs/alias.md", "old_text": "CONSTITUTION v1", "new_text": "AMENDED"})
    assert not result.success and _AD in (result.error or "")
    assert _unchanged(swe_root)


async def test_the_swe_tools_log_a_refusal_without_the_callers_path(
    swe_root: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """T37 (A1, F1): the refusal's log line carries the operation and a reason code, not the caller's path.

    Driven with the strict effect context (as ``test_strict_list_files_logging_omits_raw_arguments`` in
    ``tests/test_ad1316_real_effect_routes.py``) and without it; the returned error still names the path.
    """
    caplog.set_level("WARNING", logger=swe_tools.__name__)
    sentinel = f"SENTINEL_PRIVATE_DIR/{CONSTITUTION_RELATIVE_PATH}"
    for context in ({"_effect_dispatch_context": object()}, None):
        written = await WriteFileTool(SimpleNamespace()).invoke({"path": sentinel, "content": "AMENDED\n"}, context)
        edited = await EditFileTool(SimpleNamespace()).invoke(
            {"path": sentinel, "old_text": "CONSTITUTION v1", "new_text": "AMENDED"}, context,
        )
        for result in (written, edited):
            assert not result.success and _AD in (result.error or ""), context
            assert "SENTINEL_PRIVATE_DIR" in (result.error or ""), "the returned error keeps the path"
    assert "SENTINEL_PRIVATE_DIR" not in caplog.text
    assert "operation=write_file reason_code=constitution_refused" in caplog.text
    assert "operation=edit_file reason_code=constitution_refused" in caplog.text
    assert not (swe_root / "SENTINEL_PRIVATE_DIR").exists()


class _ShiftingPath:
    """A caller's path whose text is *first* at its first conversion and *then* afterwards (A1, F2)."""

    def __init__(self, first: str, then: str) -> None:
        self.conversions = 0
        self._first, self._then = first, then

    def __str__(self) -> str:
        self.conversions += 1
        return self._first if self.conversions == 1 else self._then


async def test_the_swe_tools_judge_the_text_they_write(swe_root: Path) -> None:
    """T38 (A1, F2): the tool converts the path once; the rule judges the text it then writes and returns."""
    ship = "config/standing_orders/ship.md"
    written = _ShiftingPath(ship, CONSTITUTION_RELATIVE_PATH)
    result = await WriteFileTool(SimpleNamespace()).invoke({"path": written, "content": "SHIP v2\n"})
    assert result.success, result.error
    assert written.conversions == 1
    assert result.output["path"] == ship
    assert (swe_root / ship).read_text(encoding="utf-8") == "SHIP v2\n"
    assert _unchanged(swe_root)
    edited = _ShiftingPath(ship, CONSTITUTION_RELATIVE_PATH)
    result = await EditFileTool(SimpleNamespace()).invoke({"path": edited, "old_text": "v", "new_text": "V"})
    assert result.success, result.error
    assert edited.conversions == 1
    assert result.output == {"replacements": 1, "path": ship}
    assert (swe_root / ship).read_text(encoding="utf-8") == "SHIP V2\n"
    assert _unchanged(swe_root)
```

### A1-T4 test file (T36 docstring)

SEARCH:
```python
    """T36: no script, hook or workflow calls the rule (acceptance 4: no friction)."""
```
REPLACE:
```python
    """T36: no tracked script, hook or workflow with a suffix in ``_CHANNEL_SUFFIXES`` names the rule or ``_names_constitution`` (acceptance 4: no friction)."""
```

### A1-D `DECISIONS.md`

SEARCH:
```markdown
- *D9.* Each writer refuses in its existing error shape. In the SWE tools the call is the first statement of the `try` that already held `str(path)`.
```
REPLACE:
```markdown
- *D9.* Each writer refuses in its existing error shape. In the SWE tools the first statement of the `try` that already held `str(path)` is that one conversion; the rule, the path resolution and the returned path use its result.
- *Amendment A1 (round-1 review F1 to F4).* D20: the SWE tools' refusal log line is a constant naming the operation and the reason code `constitution_refused`, with and without the strict effect context, so it holds no caller path (T37); the returned error is unchanged. D21: one conversion of the caller's path inside the existing `try` (T38). D22: an exception class name enters a reason when it is an exact-`str` identifier, else `Exception` (T39). D23: `builder_write_refusal`'s first statement, as on the base, calls `replace` on its argument; recorded on #1523, and the claim that it runs none of the value's code is narrowed to the rule. Rejected: keeping the path in the log outside the strict context; no log line; narrowing the one-line claims instead of D22; moving the builder's lexical check above its first statement.
```

`PROGRESS.md`: no edit. Its claims ("one-line reason"; the rule refuses a value that is not an exact `str`) hold after D22, and it says nothing about logs or about the builder running no code.

### A1-C contract prose (`prompts/ad-1344-s1-constitution-write-refusal.md`)

C1 SEARCH: `| D14 | Case 1: the rule and \`builder_write_refusal\` refuse a value that is not an exact \`str\`, before reading anything of it.`
REPLACE: `| D14 | Case 1: the rule refuses a value that is not an exact \`str\` before reading anything of it; \`builder_write_refusal\` returns that refusal from the lexical check after its empty-path check (A1, D23).`

C2 SEARCH: `Writers pass exact strings: \`str(path)\`, \`str(p)\`, \`str(target)\`.`
REPLACE: `Writers pass the result of \`str()\`: \`str(path)\` (once, A1 D21), \`str(p)\`, \`str(target)\`.`

C3 SEARCH: `| T8 | A non-exact \`str\` is refused and none of its code runs | rule, builder |`
REPLACE: `| T8 | A non-exact \`str\` is refused by the rule, which runs none of its code, and by the builder boundary | rule, builder |`

C4 SEARCH: `2. Each refusal string contains \`AD-1344\` and no line break. The only value it formats is an exact \`str\` through \`repr\`; the non-\`str\` reason formats nothing.`
REPLACE: `2. Each refusal string contains \`AD-1344\` and no line break. It formats exact \`str\` values: the path through \`repr\`, and an exception class name that is an identifier, else the literal \`Exception\` (A1 D22, T39). The non-\`str\` reason formats nothing.`

C5 SEARCH: `8. The constitution's location is defined only in \`standing_orders.py\`, and no module outside it reads \`_DEFAULT_ORDERS_DIR\` (grep).`
REPLACE: `8. \`CONSTITUTION_FILENAME\`, \`CONSTITUTION_RELATIVE_PATH\` and \`constitution_path()\` are defined in \`standing_orders.py\`, and \`builder_paths.py\` takes the location from them. (Read-side, as on the base: \`experience/commands/commands_directives.py:20-22\` reads \`_DEFAULT_ORDERS_DIR\` and \`:48\` compares the literal \`"federation.md"\`; recorded on #1523.)`

C6 SEARCH: `4. The campaign of record kills every row of the mutation table (42 rows).`
REPLACE: `4. The campaign of record kills every row of the mutation table (56 rows with Amendment A1).`

### Mutation rows (A1; replaces rows W1 to W4, B21a and B21b, and adds the rest)

| ID | File | Line (stripped) → mutant | Killed by |
|---|---|---|---|
| W1 | tools.py | `refused = constitution_write_refusal(path_text, _PROJECT_ROOT)  # AD-1344: write_file` → `refused = None` | T23, T26 |
| W2 | tools.py | same → `refused = constitution_write_refusal(path_text, None)` | T25 |
| W3 | tools.py | `refused = constitution_write_refusal(path_text, _PROJECT_ROOT)  # AD-1344: edit_file` → `refused = None` | T27 |
| W4 | tools.py | same → `refused = constitution_write_refusal(path_text, None)` | T28 |
| W13 | tools.py | `target = _resolve_path(path_text)  # AD-1344: write_file, the text the rule judged` → `target = _resolve_path(str(path))` | T38 |
| W14 | tools.py | `output={"path": path_text, "bytes_written": len(str(content))}` → `output={"path": str(path), "bytes_written": len(str(content))}` | T38 |
| W15 | tools.py | W1's line → `refused = constitution_write_refusal(str(path), _PROJECT_ROOT)  # AD-1344: write_file` | T38 |
| W16 | tools.py | `target = _resolve_path(path_text)  # AD-1344: edit_file, the text the rule judged` → `target = _resolve_path(str(path))` | T38 |
| W17 | tools.py | `return ToolResult(output={"replacements": count, "path": path_text})` → `return ToolResult(output={"replacements": count, "path": str(path)})` | T38 |
| W18 | tools.py | W3's line → `refused = constitution_write_refusal(str(path), _PROJECT_ROOT)  # AD-1344: edit_file` | T38 |
| W19 | tools.py | `logger.warning("AD-1344 WriteFileTool refused operation=write_file reason_code=constitution_refused")` → `logger.warning("AD-1344 WriteFileTool refused: %s", refused)` | T37 |
| W19b | tools.py | same → `pass` | T37 |
| W20 | tools.py | `logger.warning("AD-1344 EditFileTool refused operation=edit_file reason_code=constitution_refused")` → `logger.warning("AD-1344 EditFileTool refused: %s", refused)` | T37 |
| W20b | tools.py | same → `pass` | T37 |
| W21 | tools.py | `path_text = str(path)  # AD-1344: write_file, the one conversion` → `path_text = path` | T38 |
| W22 | tools.py | `path_text = str(path)  # AD-1344: edit_file, the one conversion` → `path_text = path` | T38 |
| B21a | builder_paths | `if type(cls) is not type:` → `if False:` | T15 |
| B21b | builder_paths | `return name if type(name) is str and name.isidentifier() else "Exception"` → `return "Exception"` | T13 |
| B21c | builder_paths | same → `return name if name.isidentifier() else "Exception"` | T39 |
| B21d | builder_paths | same → `return name if type(name) is str else "Exception"` | T39 |

A failed assertion kills each new row. W13 and W16 fail `conversions == 1`. W14 and W17 fail on the returned path or the conversion count. W15 and W18 fail `result.success`, because the second conversion is the constitution. W21 and W22 fail `result.success`, because the rule refuses a value that is not an exact `str`. W19 fails on the sentinel in the log, and W19b on the missing reason code (W20 and W20b the same). B21a returns `Spoofed`, B21b returns `Exception` where T13 expects `PermissionError`, and B21c and B21d both fail `(target: Exception)`. None depends on a fixture error.

**Rerun:** every row. `builder_paths.py`, `tools.py` and the test file all change, and the test file holds every killer.

