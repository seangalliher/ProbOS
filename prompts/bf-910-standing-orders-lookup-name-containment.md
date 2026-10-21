# BF-910: `standing_orders_lookup` selects a name from the loader's flat directory, never a path, and reads through the BF-758 floor

**`department` becomes one name chosen from the standing-orders files that exist, read with the verified reader the source tool uses. This closes the traversal (#1608) and also repairs a tool that has never returned a file.**

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-20
**Status:** Ready for dry run · **Issue:** #1608 · **Tier:** HIGH (security: a path traversal reachable from ensign rank; confirmed, not lowered)
**Dependencies:** none (base `origin/main` `5282b6e61beb4acc786dfedd6a3cd232a88e3eac`, BF-908 merged)
**Estimated tests:** 1 new file, about 75 test cases once parametrised; 0 existing tests change
**Files:** `src/probos/cognitive/standing_orders.py`, `src/probos/cognitive/swe_harness/tools.py`, `tests/test_bf910_standing_orders_lookup.py` (new), `PROGRESS.md`, `DECISIONS.md`

---

## Problem

### 1. The traversal (#1608)

`StandingOrdersLookupTool.invoke` (`src/probos/cognitive/swe_harness/tools.py:834-859`) builds a path from the caller's `department` value with no validation, then reads it:

```
tools.py:850                 dept = params.get("department") or "engineering"
tools.py:851                 target = base / "departments" / f"{dept}.md"
tools.py:853                 dept = params.get("department") or "engineering"
tools.py:854                 target = base / "departments" / f"{dept}.md"
tools.py:857             return ToolResult(output=target.read_text(encoding="utf-8"))
```

If `department` holds `..` segments or an absolute path, `target` can be any `.md` file the vessel's OS user can read. The tool is registered with `read_perms` (`tools.py:1322`), so every rank from ensign up can call it. It never calls the BF-758 floor. The issue reproduced this with synthetic markers. The reach is read-only and limited to `.md` files. The not-found text echoes the value (`tools.py:856`, `target.name`), and so does the catch-all (`tools.py:859`, `{exc}`, whose text holds the path).

### 2. The tool has never returned a file (new finding; #1608 does not know this)

The tool fails on two separate counts. Both date from its first commit, `e5fdafc7` (2026-05-07, AD-543..549):

| | Evidence |
|---|---|
| **(a) Wrong root.** `_PROJECT_ROOT = Path(__file__).resolve().parents[3]` (`tools.py:70`). `tools.py` is at `src/probos/cognitive/swe_harness/tools.py`, so `parents[3]` is **`<checkout>/src`**, not the checkout. The base on `tools.py:845` is therefore `<checkout>/src/config/standing_orders`, which does not exist (Glob `src/config/**`: no files). Every *other* module that roots `config/` is one directory shallower and uses four `.parent` steps to reach the checkout: `standing_orders.py:35`, `copilot_adapter.py:55`, `task_context.py:14`. The `src/` root is deliberate for `read_file` relative paths and is pinned by `tests/test_bf758_file_read_confinement.py:404-413` (`_PROJECT_ROOT / "probos/security/file_access.py"`), so it stays as it is. | `git log -S "parents[3]"` on `tools.py` → only `e5fdafc7` |
| **(b) Wrong layout.** `config/standing_orders/` is **flat**. It holds 27 `.md` files (`ship.md`, `federation.md`, `bridge.md`, `engineering.md`, `medical.md`, `science.md`, `security.md`, `architect.md`, `builder.md`, …) and one directory, `crew_profiles/`. There is no `departments/` directory, and there never was one in any ref (`git log --all --oneline -- config/standing_orders/departments` returns nothing). The loader that composes standing orders into every agent's prompt reads the department tier and the agent tier from the **same** flat directory: `compose_instructions` reads `d / f"{dept}.md"` (`standing_orders.py:456`) and `d / f"{agent_type}.md"` (`:461`), and `get_order_tiers` does the same (`:146-147`). The module docstring (`standing_orders.py:6-10`) lists `{department}.md` and `{agent}.md` as siblings of `ship.md`. | `ls config/standing_orders` |
| **(c) `agent` scope = `department` scope.** The `agent` branch (`tools.py:852-854`) is a copy of the `department` branch. The schema declares no `agent` parameter (`tools.py:818-825`), and the AD-1179 golden fixture pins that schema byte for byte (`tests/fixtures/ad1179_tool_definition_golden.json:45`). | |

So today all three scopes, `ship` included, return `Standing orders not found: <x>.md` for every honest call. Only a traversal value reaches a real file. No code or test depends on the "not found" result; see **Absence Verified**.

---

## Decisions

| # | Decision | Reason / evidence | What would change it |
|---|---|---|---|
| **D1** | **Scope (b):** validation and containment, **plus** reading the real flat layout from the loader's directory, so `ship`, `department` and `agent` return real files. | Under (a), a "real names still resolve" test is impossible: nothing resolves today, so the fix could not be shown to keep the honest path working. The repair is the same few lines: once the base is taken from the loader, the layout problem goes away. No caller depends on today's "not found" (Absence Verified). A legitimate caller now receives the text the agent was always meant to see. That text is already composed into its system prompt, so it discloses nothing new. | A caller found that relies on "not found". |
| **D2** | **The value is a name, never a path.** It must be an exact `str` (`type(v) is str`, so a subclass is refused, per architect order 4), fully matching `[A-Za-z0-9_-]{1,64}` (`re.fullmatch`, ASCII ranges only, not `\w`). It must **also** be an exact member of the names listed from the directory (`<stem>.md` directly in it, case-sensitive). The path is then `resolved_base / f"{name}.md"`, where `name` is proven equal to a listed stem. | The shape check refuses `..`, `.`, `/`, `\`, `:` (drive, stream), NUL, control characters, space, a trailing dot or space, Unicode look-alikes, empty values and anything over 64 characters, all before any I/O. The listing check makes case behave the same on every OS (`Engineering` is not found on Windows either). It also means a Windows device name (`CON`, `NUL`, `AUX`, `COM1`, `LPT1`, `PRN`, which match the shape) is never opened, because none is listed. Reading `CON.md` on Windows can block on the console. Both checks follow CWE-22's "map the input to a known name; reject, don't strip". | — |
| **D3** | **Defaults and the absence of a value are unchanged.** If `department` is absent, `None` or `""`, it means `engineering` for both the `department` and `agent` scopes. The `ship` scope ignores `department`, as today. Any other non-string value (`0`, `False`, `[]`, `{}`, `5`, bytes, a str subclass) is **refused**. Today the falsy ones fell to `engineering`. | The `or "engineering"` idiom (`tools.py:850`) let falsy non-strings through. The schema says `string`, so a non-string value is a caller error, and reporting it is the AD-1179 doctrine (`protocol.py:175-179`: an error is correctable; a confident wrong answer is not). | — |
| **D4** | **The `agent` scope selects by name from the same directory as `department`.** The schema is unchanged: there is still no `agent` parameter, and the description, enum and golden bytes stay the same. | The loader stores both tiers as `<name>.md` in one directory (`standing_orders.py:456,461`), so a structural distinction between the scopes would be invented. Adding an `agent` parameter would change the AD-1179 golden wire bytes, which is a separate change. | An AD that reshapes the tool schema. |
| **D5** | **The base is the loader's directory**: a new public `standing_orders.standing_orders_dir()`, which returns `_DEFAULT_ORDERS_DIR` (`standing_orders.py:35`, `<checkout>/config/standing_orders`). It is read at each call and **resolved once** before the listing (`Path.resolve()`). The constructor gains `orders_dir: Path | None = None` (constructor injection, for tests). The registration call at `tools.py:1322` is unchanged. | This gives one owner for the layout: the tool reads exactly the files the agents' prompts are composed from. A public accessor replaces a cross-module private read (`commands_directives.py:20` already reads `_DEFAULT_ORDERS_DIR` directly; it is left alone). Both `_DEFAULT_ORDERS_DIR` and the old base assume a source checkout. ProbOS runs from its checkout (editable install). In a non-checkout install the directory is absent, the listing is empty, and the tool answers "not found; available: none". That is no worse than today. **If the base itself is a link or junction** (an operator choice), resolving it first follows it once. Containment and reads are then judged against the resolved directory, so the tool works through a linked directory (tested). | — |
| **D6** | **The read goes through the BF-758 floor *and* the operator's read policy, as a verified read:** `read_verified_file(path, protected_roots=protected_read_roots(rt), exempt_roots=workspace_exempt_roots(rt), permitted_roots=permitted_read_roots(rt) or None)`. This is exactly the call at `tools.py:328-332` (`_verified_source_result`). `resolve_for_runtime` is not called separately: `read_verified_file` calls `resolve_read_path` with the same three root sets (`file_access.py:726-730`). | **What it adds:** (1) the floor, so this tool can no longer return a protected file even through an operator's link; this closes this tool's entry in BF-908 R9 / #1523 F-202 (`prompts/bf-908-…md:4224`). (2) **Link refusal:** `read_verified_file` refuses a path whose resolution differs from its spelling (`file_access.py:731-732`), so a `<name>.md` symlink inside the directory that points outside is refused. That is the containment check: the candidate is `resolved_base / <listed name>`, so it can only escape through a link, and links are refused. (3) A pinned read that refuses a reparse point or a non-regular file (`file_access.py:704-718, 561-567`) and detects a swap during the read. (4) `validate_read_location` refuses reserved device names (`file_access.py:342`). (5) The operator's `read_roots` policy. It is empty by default (`file_access.py:158-169`), so by default the behaviour is the floor alone. **What it could break:** a vessel whose operator confined reads with `security_infra.read_roots` to roots that exclude the checkout will see this tool refuse. That is the policy doing its job, and the agent still receives the same text through its composed prompt. A policy that applies to every tool read is simpler for the operator than one with exceptions. The floor needs no runtime: `runtime=None` falls back to the platform data directory (`file_access.py:231-239`). | An operator requirement that standing orders stay readable under confinement (then pass `permitted_roots=None`; this would be a Captain call because it exempts a reader from policy). |
| **D7** | **No error echoes the value or a path.** The shape refusal is fixed text. Not-found is `Standing orders not found for that name; available: <listed names>`, which helps the agent and contains no caller text. A floor or policy refusal is fixed text. Any other failure is `standing_orders_lookup failed: <ExceptionType>`, with only the type logged at WARNING. Every result keeps the existing `ToolResult(error=...)` shape. The scope refusal (`tools.py:842-844`) is unchanged, because `tests/test_ad1179_vocabulary_constants.py:116-118` pins it. | The issue asks that no refusal echo the value. The old `{exc}` text carried the path. The available-names list comes from the public repository's file names. | — |
| **D8** | **Output parity:** the bytes are decoded as `Path.read_text(encoding="utf-8")` did, with universal newlines, through `io.TextIOWrapper(..., newline=None)`. This is the precedent at `tools.py:347-350`. | On a Windows checkout with CRLF line endings, the agent sees `\n`, as `read_text` gave. | — |
| **D9** | **The helpers live in `standing_orders.py`**, the layout owner: `is_standing_order_name`, `standing_orders_dir` and `standing_order_names`. They are public, so the sibling Copilot handler (follow-up F1) can reuse them without importing a private name from `tools.py`. | Dependency direction: `swe_harness/tools.py` imports from `cognitive/standing_orders.py`, which imports no `swe_harness` module, and `crew_profile`'s module-level imports are TYPE_CHECKING-only or function-local (`crew_profile.py:25,40`). | — |
| **D10** | **No source-scan guard.** The behavioural spies are the guard: every `read_verified_file` call is checked to have the resolved base as its parent, and no `.md` file may be read with `Path.read_text`. | A `?raw`-style scan cannot tell a required line from a shipped one (the BF-707/710/717/720 anti-pattern). | — |

---

## Solution overview

1. `standing_orders.py` gains three public helpers: the name shape, the default directory, and the listing of selectable names.
2. `StandingOrdersLookupTool` works in this order: scope gate (unchanged) → choose the name (`ship` or `department`, default `engineering`) → shape check (fixed refusal) → resolve the base → listing membership (not-found, listing the available names) → `read_verified_file` under floor and policy → universal-newline decode.
3. One new test file proves: refusals for every malformed form in both scopes, with a synthetic outside marker the test can read directly; real names; the default; not-found; case; device names; a link inside the directory; a linked directory; floor; policy; no echo; output parity; and the shipped default directory resolving real files.

---

## Milestones (about 50 tool calls each at most)

| Milestone | Sections | Focused check (run with `-n 0`) |
|---|---|---|
| **M1** helpers | Section 1; tests T19-T20 | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf910_standing_orders_lookup.py -k "names or name_shape" -n 0 -q` · `tests/test_standing_orders.py -n 0 -q` |
| **M2** tool | Sections 2-3; tests T1-T18 | `tests/test_bf910_standing_orders_lookup.py tests/test_ad544_native_tools.py tests/test_ad1179_vocabulary_constants.py tests/test_ad1179_tool_schema_golden.py tests/test_ad1179_schema_vocabulary_guards.py tests/test_bf758_file_read_confinement.py tests/test_bf892_spawn_env_guard.py tests/test_bf890_command_env.py tests/test_standing_orders.py tests/test_standing_orders_layout.py -n 0 -q` · import smoke: `d:/ProbOS/.venv/Scripts/python.exe -c "import probos.cognitive.swe_harness.tools, probos.runtime"` |
| **M3** trackers + mutation | Section 4; mutation table | The 21 rows against `tests/test_bf910_standing_orders_lookup.py`, plus `tests/test_standing_orders_layout.py` once on the final tree (it scans `src/` and `tests/` for retired names: `probos-architect`, `probos-builder`, `probos-diff-reviewer`, `ProbOS Supervised`, `supervised-worker.json`, `tests/test_standing_orders_layout.py:144,151`; none may appear in the new files) |

The broad gate runs once, after the Diff Reviewer, from the main session (`scripts/run_test_gate.py --label bf-910 --receipt logs/gates/bf-910.receipt.json`). Stage explicit paths only. Never use `git add -A`.

---

## Section 1: `src/probos/cognitive/standing_orders.py`: the name shape, the directory, the listing

`re` and `Path` are already imported (`standing_orders.py:16-17`).

```
<<<<<<< SEARCH
def register_department(agent_type: str, department: str) -> None:
    """Register an agent type's department assignment.

    Used by dynamically designed agents to declare their department.
    """
    _AGENT_DEPARTMENTS[agent_type] = department


def set_directive_store(store: Any) -> None:
=======
def register_department(agent_type: str, department: str) -> None:
    """Register an agent type's department assignment.

    Used by dynamically designed agents to declare their department.
    """
    _AGENT_DEPARTMENTS[agent_type] = department


# BF-910: a standing-orders name is one file stem in the flat directory, never a
# path. ASCII letters, digits, '_' and '-', 1 to 64 characters: no dot, slash,
# backslash, colon, NUL or space, so no '..', absolute, drive, UNC, stream or
# trailing-dot form can be spelled.
_STANDING_ORDER_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")


def is_standing_order_name(value: object) -> bool:
    """BF-910: True for an exact ``str`` (never a subclass) of the name shape."""
    return type(value) is str and _STANDING_ORDER_NAME.fullmatch(value) is not None


def standing_orders_dir() -> Path:
    """BF-910: the directory :func:`compose_instructions` reads by default."""
    return _DEFAULT_ORDERS_DIR


def standing_order_names(orders_dir: Path | None = None) -> tuple[str, ...]:
    """BF-910: the names a caller may select, sorted: each ``<name>.md`` directly in the directory.

    A source of names, not an authority: the caller reads through a verified
    reader. A missing or unreadable directory has no names.
    """
    d = orders_dir or _DEFAULT_ORDERS_DIR
    try:
        stems = [entry.name[:-3] for entry in d.iterdir() if entry.name.endswith(".md")]
    except OSError:
        return ()
    return tuple(sorted(stem for stem in stems if is_standing_order_name(stem)))


def set_directive_store(store: Any) -> None:
>>>>>>> REPLACE
```

`standing_orders_dir()` reads the module global at call time, so a test that monkeypatches `_DEFAULT_ORDERS_DIR` still sees its own value.

---

## Section 2: `src/probos/cognitive/swe_harness/tools.py`: import

```
<<<<<<< SEARCH
from typing import Any, TYPE_CHECKING

from probos.execution.command_env import build_command_env
=======
from typing import Any, TYPE_CHECKING

from probos.cognitive.standing_orders import (
    is_standing_order_name,
    standing_order_names,
    standing_orders_dir,
)
from probos.execution.command_env import build_command_env
>>>>>>> REPLACE
```

`FileAccessDenied`, `permitted_read_roots`, `protected_read_roots`, `read_verified_file` and `workspace_exempt_roots` are already imported (`tools.py:48-55`), and so are `io` and `Path` (`:15`, `:20`).

---

## Section 3: `src/probos/cognitive/swe_harness/tools.py`: the tool

### 3a: fixed texts and docstring

```
<<<<<<< SEARCH
_STANDING_ORDERS_SCOPES: tuple[str, ...] = ("ship", "department", "agent")


class StandingOrdersLookupTool:
    """AD-544: Read a standing-orders manual file."""
=======
_STANDING_ORDERS_SCOPES: tuple[str, ...] = ("ship", "department", "agent")

# BF-910: fixed texts, so no refusal or failure echoes the caller's value or a path.
_STANDING_ORDERS_NAME_REFUSAL = (
    "department must name one standing-orders file: 1 to 64 ASCII letters, "
    "digits, '_' or '-', for example 'engineering'"
)
_STANDING_ORDERS_DENIED = (
    "standing_orders_lookup: that standing-orders file is not readable on this vessel"
)


class StandingOrdersLookupTool:
    """AD-544: Read a standing-orders manual file.

    BF-910: ``department`` selects one name from the flat directory the loader
    composes agents' standing orders from (``standing_orders_dir()``); it is
    never joined into a path unchecked, and the read is a verified read under
    the BF-758 floor and the operator's read policy.
    """
>>>>>>> REPLACE
```

Neither fixed text contains a `.` character. Test T2 relies on this to check that the value `..` is not echoed.

### 3b: constructor and `invoke`

```
<<<<<<< SEARCH
    def __init__(self, runtime: "ProbOSRuntime") -> None:
        self._runtime = runtime

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        scope = params.get("scope")
        if scope not in _STANDING_ORDERS_SCOPES:
            return ToolResult(
                error="scope must be one of " + "|".join(_STANDING_ORDERS_SCOPES)
            )
        base = _PROJECT_ROOT / "config" / "standing_orders"
        try:
            if scope == "ship":
                target = base / "ship.md"
            elif scope == "department":
                dept = params.get("department") or "engineering"
                target = base / "departments" / f"{dept}.md"
            else:
                dept = params.get("department") or "engineering"
                target = base / "departments" / f"{dept}.md"
            if not target.exists():
                return ToolResult(error=f"Standing orders not found: {target.name}")
            return ToolResult(output=target.read_text(encoding="utf-8"))
        except Exception as exc:
            return ToolResult(error=f"standing_orders_lookup failed: {exc}")
=======
    def __init__(self, runtime: "ProbOSRuntime", orders_dir: Path | None = None) -> None:
        self._runtime = runtime
        # BF-910: None reads the loader's directory at each call; tests inject one.
        self._orders_dir = orders_dir

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        scope = params.get("scope")
        if scope not in _STANDING_ORDERS_SCOPES:
            return ToolResult(
                error="scope must be one of " + "|".join(_STANDING_ORDERS_SCOPES)
            )
        name: object = "ship"
        if scope != "ship":
            # The department and agent tiers are both <name>.md in the one flat
            # directory (compose_instructions), so both scopes select by name.
            name = params.get("department")
            if name is None or name == "":
                name = "engineering"
        # BF-910: a name, never a path; the refusal never echoes the value.
        if not is_standing_order_name(name):
            return ToolResult(error=_STANDING_ORDERS_NAME_REFUSAL)
        try:
            base = (self._orders_dir or standing_orders_dir()).resolve()
            names = standing_order_names(base)
            if name not in names:
                return ToolResult(
                    error="Standing orders not found for that name; available: "
                    + (", ".join(names) or "none")
                )
            # BF-910: the floor, the operator's read policy and a pinned,
            # link-refusing read, exactly as the verified source read does.
            snapshot = read_verified_file(
                base / f"{name}.md",
                protected_roots=protected_read_roots(self._runtime),
                exempt_roots=workspace_exempt_roots(self._runtime),
                permitted_roots=permitted_read_roots(self._runtime) or None,
            )
            # Path.read_text's UTF-8 and universal-newline output, as before.
            with io.TextIOWrapper(io.BytesIO(snapshot.data), encoding="utf-8", newline=None) as text:
                return ToolResult(output=text.read())
        except FileAccessDenied:
            return ToolResult(error=_STANDING_ORDERS_DENIED)
        except Exception as exc:
            logger.warning("BF-910: standing_orders_lookup read failed: %s", type(exc).__name__)
            return ToolResult(error=f"standing_orders_lookup failed: {type(exc).__name__}")
>>>>>>> REPLACE
```

Exception tiers: `FileAccessDenied` is a deliberate refusal (fixed text). Every other exception (`OSError` from a race, `ValueError` from `validate_read_location`, `UnicodeDecodeError`) is log-and-degrade, with only the type logged, which matches the tool's old catch-all. `_PROJECT_ROOT` keeps its other users (`tools.py:239, 439, 534, 745`).

---

## Section 4: trackers

**PROGRESS.md**: add a new paragraph as line 3, above the BF-908 paragraph:

> **BF-910 (2026-10-20), #1608 -- `standing_orders_lookup` takes a standing-orders name, never a path, and reads the real files: a `department` value is one name from `config/standing_orders/` (1 to 64 ASCII letters, digits, `_` or `-`, and a file that exists there), read through the BF-758 floor and the operator's read policy, so `..`, absolute, drive, UNC and link forms no longer reach any `.md` file the vessel's user can read.** The tool also never returned a file before this fix: its base was `src/config/standing_orders/departments/` (its module root is `src/`, and the directory is flat), so every scope, `ship` included, answered "not found". It now reads the directory that agents' standing orders are composed from. The `department` and `agent` scopes both select by name; an unknown name lists the available ones; no error echoes the value. The Copilot visiting-session handler with the same defect is a follow-up.

**DECISIONS.md**: insert immediately after the BF-908 entry's `- *Reversal.*` line (`DECISIONS.md:396`):

```markdown
### BF-910 -- standing_orders_lookup selects a name from the loader's flat directory and reads it through the BF-758 floor (2026-10-20, #1608)

- *Scope (D1).* Validation, containment and the real layout together: the tool had never returned a file (its base was `<checkout>/src/config/standing_orders/departments/`, from `tools.py`'s `src/` root and a `departments/` directory that never existed), so a "real names still resolve" test was only possible once the layout was right. Contract: `prompts/bf-910-standing-orders-lookup-name-containment.md`.
- *D2 (a name, never a path).* An exact `str` fully matching `[A-Za-z0-9_-]{1,64}`, and an exact, case-sensitive member of the `<stem>.md` files listed directly in the directory; the path is the resolved directory joined with that listed name. Device names are never opened because none is listed.
- *D5/D6 (base and read).* The base is `standing_orders.standing_orders_dir()` (the loader's `_DEFAULT_ORDERS_DIR`), resolved once; the read is `read_verified_file` with the floor, the workspace exemption and the operator's `read_roots` policy, as `_verified_source_result` does, so a link inside the directory is refused and a linked directory works.
- *D3/D4 (compatibility).* Absent, `None` or `""` still means `engineering`; other non-strings are refused; the `agent` scope selects by name from the same directory; the schema and the AD-1179 golden are unchanged.
- *Residual.* A hard link or a same-user process writing into `config/standing_orders/` is not distinguishable from a standing order. The Copilot adapter's `_handle_standing_orders` has the same defect (follow-up issue).
- *Mutation campaign of record.* <filled at M3: tree, rows killed, first failing test per row, sha256 of the two source files and the test file>.
- *Reversal.* Revert the BF-910 commit. Nothing persisted is touched.
```

**`docs/development/roadmap.md`**: no row. Its Bug Tracker section (`roadmap.md:1131-1134`) points to GitHub issues and has no table, which matches BF-906 D12 (`DECISIONS.md:219`).

---

## Tests: `tests/test_bf910_standing_orders_lookup.py` (new)

All state lives in `tmp_path`. No live runtime data is touched. Nothing sleeps. T13 reads the tracked checkout's `config/standing_orders/` read-only. Async tests use `@pytest.mark.asyncio`, as `tests/test_ad1179_vocabulary_constants.py:113` does.

**Fixtures**

- `orders`: `tmp_path/"checkout"/"config"/"standing_orders"` with `ship.md` = `SHIP-ORDERS`, `engineering.md` = `ENG-ORDERS`, `builder.md` = `BUILDER-ORDERS`, `science.md` = `SCI-ORDERS`, plus `crew_profiles/deep.md` = `MARKER-BF910-DEEP`. Write with `write_text`.
- Outside markers: `tmp_path/"checkout"/"config"/"secret.md"` = `MARKER-BF910-CONFIG` and `tmp_path/"secret.md"` = `MARKER-BF910-ROOT`.
- `_runtime(tmp_path, read_roots=())`: `SimpleNamespace(data_dir=tmp_path/"data", config_path=None, config=SimpleNamespace(execution=SimpleNamespace(workspace_root=str(tmp_path/"data"/"execution"/"workspaces")), security_infra=SimpleNamespace(read_roots=[str(r) for r in read_roots])))`. Create the workspace directory, following the shape of `tests/test_bf758_file_read_confinement.py:26-35`.
- `reads` (monkeypatch spies): wrap `probos.cognitive.swe_harness.tools.read_verified_file`, recording `Path(path)` and calling the real function captured before patching. Wrap `Path.read_text`, recording `self`. Install the spies after the files are written.
- `_junction(link, target)`: `_winapi.CreateJunction` on Windows and `symlink_to(..., target_is_directory=True)` elsewhere. Remove it in a `finally` (`rmdir` on Windows, `unlink` elsewhere), as in `tests/test_ad1200_instruction_file_access.py:36-49`.
- A `_Str(str)` subclass.

**Cases**

| # | Name | What it proves | What it does not prove |
|---|---|---|---|
| T1 | `test_premise_the_outside_markers_are_readable` | A direct `read_text` of each marker returns it, so any later refusal comes from the tool, not from the filesystem. | — |
| T2 | `test_a_name_that_is_not_one_segment_is_refused[scope][value]`. Scope ∈ {`department`, `agent`} × value ∈ {`"../secret"`, `"..\\secret"`, `"../../secret"`, `".."`, `"."`, `"crew_profiles/deep"`, `"crew_profiles\\deep"`, `"engineering/../secret"`, `str(tmp_path/"secret")`, `str(tmp_path/"secret.md")`, `"C:secret"`, `"C:\\secret"`, `"\\\\server\\share\\secret"`, `"//server/share/secret"`, `"\\\\?\\C:\\secret"`, `"engineering\x00"`, `"engineering."`, `"engineering "`, `" engineering"`, `"engineering\n"`, `"engineering::$DATA"`, `"engi neering"`, `"%2e%2e%2fsecret"`, `"ｅｎｇｉｎｅｅｒｉｎｇ"`, `"x"*65`, `"x"*10000`} | `result.error == tools._STANDING_ORDERS_NAME_REFUSAL`, `result.output is None`, `value not in result.error`, no marker text anywhere in the result, `reads.verified == []`, and no `.md` in `reads.plain`. The shape check runs before any I/O. | That every possible bypass is covered: the allowlist is the proof, and these cases are a sample. |
| T3 | `test_a_non_string_department_is_refused[scope][value]`. Value ∈ {`0`, `False`, `True`, `5`, `1.5`, `["engineering"]`, `{"a": 1}`, `b"engineering"`, `_Str("engineering")`} | The same refusal and no reads. D3: a falsy non-string no longer falls back to the default. A str subclass is refused. | — |
| T4 | `test_real_names_resolve[scope, params, expected]`: (`ship`, `{}`, SHIP), (`ship`, `{"department": "../secret"}`, SHIP), (`department`, `{"department": "engineering"}`, ENG), (`department`, `{"department": "science"}`, SCI), (`agent`, `{"department": "builder"}`, BUILDER) | Output equals the file text. `reads.verified` holds exactly one path, `orders.resolve()/"<name>.md"`, so its parent is the resolved base. No `.md` in `reads.plain`. The `ship` scope ignores `department`, as before. | — |
| T5 | `test_the_default_name_is_engineering[scope][params]`: scope ∈ {`department`, `agent`} × params ∈ {`{}`, `{"department": None}`, `{"department": ""}`} | Output is ENG (D3). | — |
| T6 | `test_an_unknown_name_is_not_found_and_lists_the_names` (`"nosuch"`, `"crew_profiles"`) | Error is `"Standing orders not found for that name; available: builder, engineering, science, ship"`. `"nosuch"` is not in the error. No reads. `crew_profiles` (a directory) is not a name. | — |
| T6b | `test_a_missing_directory_has_no_names` (`orders_dir=tmp_path/"absent"`) | Error ends in `available: none`. No reads. | — |
| T7 | `test_case_must_match_exactly` (`"Engineering"`, `"ENGINEERING"`) | Not found on every OS, with the value not echoed and no reads. On Windows, this is the case a case-insensitive filesystem would otherwise admit. | — |
| T8 | `test_device_names_are_never_opened` (`"CON"`, `"NUL"`, `"AUX"`, `"PRN"`, `"COM1"`, `"LPT1"`) | Not found and `reads.verified == []`. Nothing is ever opened, including a console device on Windows. | — |
| T9 | `test_a_link_in_the_directory_that_points_outside_is_refused` (`orders/"leak.md"` → `tmp_path/"secret.md"`; `pytest.skip` on `OSError`/`NotImplementedError`, as `tests/test_bf758_file_read_confinement.py:148-151` does) | `"leak"` is listed. The result error is `_STANDING_ORDERS_DENIED`, and `MARKER-BF910-ROOT` is not in the result. This is containment through `read_verified_file`'s alias refusal. | Anything, on a Windows host without symlink privilege (the test skips there; Linux CI runs it). |
| T10 | `test_a_linked_directory_is_read_through_its_resolution` (`tmp_path/"linked"` junction/symlink → `orders`; tool built with `orders_dir=tmp_path/"linked"`) | `department="engineering"` returns ENG. The base is resolved before the read (D5). No privilege is needed on Windows (junction). | — |
| T11 | `test_the_floor_refuses_a_directory_inside_the_data_directory` (orders created at `tmp_path/"data"/"orders"`; `_runtime(tmp_path)`) | Error is `_STANDING_ORDERS_DENIED` and ENG is not in the result. The floor is wired into this tool. | — |
| T12 | `test_the_operator_read_policy_applies` (`read_roots=[tmp_path/"elsewhere"]` → denied; `read_roots=[tmp_path/"checkout"]` → ENG) | Policy is wired (D6), and a permitted root admits the read. | — |
| T13 | `test_the_shipped_tool_reads_the_loaders_directory` (`StandingOrdersLookupTool(_runtime(tmp_path))`, no `orders_dir`, the same call shape as `tools.py:1322`) | `standing_orders_dir() == Path(standing_orders.__file__).resolve().parents[3]/"config"/"standing_orders"`. `{"ship","engineering","builder"} <= set(standing_order_names())`. `scope=department` (default) output equals `(standing_orders_dir()/"engineering.md").read_text(encoding="utf-8")`. `scope=ship` output equals `ship.md`'s text. The real layout resolves (D1, D5), so the `src/` root is no longer used for this tool. | The registry path end to end: registration passes only `runtime` (`tools.py:1322`), which is this call. |
| T14 | `test_agent_is_not_a_parameter` (`{"scope": "agent", "agent": "builder"}`) | The `refuse_undeclared_params` error names `agent`. No reads. D4: the schema is unchanged. | — |
| T15 | `test_output_matches_read_text_newlines` (`engineering.md` written as bytes `b"A\r\nB\r\n"`) | Output is `"A\nB\n"` (D8). | — |
| T16 | `test_a_read_failure_names_only_its_type` (spy replaced by one raising `PermissionError(13, "denied", str(tmp_path/"secret.md"))`, then one raising `FileAccessDenied(str(tmp_path/"x.md"), "r")`) | Errors are exactly `"standing_orders_lookup failed: PermissionError"` and `_STANDING_ORDERS_DENIED`. `str(tmp_path)` is in neither. | — |
| T17 | `test_scope_refusal_is_unchanged` (`{"scope": "fleet", "department": "../secret"}`) | The scope refusal comes first and is unchanged. No reads. | — |
| T18 | `test_every_read_stays_in_the_base` (runs T2-T8's inputs in one loop over both scopes and checks `reads.verified` afterwards) | Every recorded path has `.parent == orders.resolve()`, and no `.md` is ever passed to `Path.read_text`. This is D10's behavioural guard. | — |
| T19 | `test_standing_order_names_lists_only_selectable_stems` (dir with `a.md`, `b-c_d.md`, `notes.txt`, `dotted.name.md`, `UPPER.MD`, `sp ace.md`, and subdirectory `crew_profiles/`) | `standing_order_names(d) == ("a", "b-c_d")`. A missing directory gives `()`. | — |
| T20 | `test_name_shape_boundaries` | `is_standing_order_name("x"*64)` is True. False for `"x"*65`, `""`, `_Str("a")`, `None`, `"a.b"`, `"a\n"`. | — |

Existing tests that must stay green without being edited: `tests/test_ad544_native_tools.py:81-84,127-147` (metadata, 12 tools registered), `tests/test_ad1179_vocabulary_constants.py:80-82,113-121` (scope constant, refusal text, description), `tests/test_ad1179_tool_schema_golden.py:57,133` with `tests/fixtures/ad1179_tool_definition_golden.json:45` (schema bytes), `tests/test_ad1179_schema_vocabulary_guards.py:257`, `tests/test_bf758_file_read_confinement.py:404-413` (`tools._PROJECT_ROOT` is `src/`; unchanged), and `tests/test_standing_orders_layout.py` (retired-name scan).

---

## Mutation table (HIGH): whole stripped lines, each unique in its file after the change

Run each row against `tests/test_bf910_standing_orders_lookup.py`. The unmutated baseline must be all passed (T9 may skip on Windows).

| # | File | Line (stripped, whole) | Mutant (whole line) | Killed by |
|---|---|---|---|---|
| 1 | tools.py | `if not is_standing_order_name(name):` | `if False:` | T2 |
| 2 | standing_orders.py | `return type(value) is str and _STANDING_ORDER_NAME.fullmatch(value) is not None` | `return isinstance(value, str) and _STANDING_ORDER_NAME.fullmatch(value) is not None` | T3[_Str], T20 |
| 3 | standing_orders.py | `_STANDING_ORDER_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")` | `_STANDING_ORDER_NAME = re.compile(r"[A-Za-z0-9_-]+")` | T2[x*65], T20 |
| 4 | standing_orders.py | `_STANDING_ORDER_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")` | `_STANDING_ORDER_NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}")` | T2[engineering.], T2[..] |
| 5 | standing_orders.py | `return type(value) is str and _STANDING_ORDER_NAME.fullmatch(value) is not None` | `return type(value) is str and _STANDING_ORDER_NAME.match(value) is not None` | T2[engineering/../secret] |
| 6 | tools.py | `if name not in names:` | `if False:` | T6, T8 |
| 7 | tools.py | `base = (self._orders_dir or standing_orders_dir()).resolve()` | `base = self._orders_dir or standing_orders_dir()` | T10 |
| 8 | tools.py | `base = (self._orders_dir or standing_orders_dir()).resolve()` | `base = (self._orders_dir or _PROJECT_ROOT / "config" / "standing_orders").resolve()` | T13 |
| 9 | tools.py | `protected_roots=protected_read_roots(self._runtime),` | `protected_roots=[],` | T11 |
| 10 | tools.py | `permitted_roots=permitted_read_roots(self._runtime) or None,` | `permitted_roots=None,` | T12 |
| 11 | tools.py | `return ToolResult(error=f"standing_orders_lookup failed: {type(exc).__name__}")` | `return ToolResult(error=f"standing_orders_lookup failed: {exc}")` | T16 |
| 12 | tools.py | `name = "engineering"` | `name = "ship"` | T5 |
| 13 | tools.py | `if name is None or name == "":` | `if name is None:` | T5[""] |
| 14 | tools.py | `name: object = "ship"` | `name: object = "federation"` | T4[ship] |
| 15 | tools.py | `if scope != "ship":` | `if True:` | T4[ship, ../secret] |
| 16 | standing_orders.py | `stems = [entry.name[:-3] for entry in d.iterdir() if entry.name.endswith(".md")]` | `stems = [entry.name[:-3] for entry in d.iterdir()]` | T19 (`crew_profi`) |
| 17 | standing_orders.py | `return tuple(sorted(stem for stem in stems if is_standing_order_name(stem)))` | `return tuple(sorted(stems))` | T19 |
| 18 | standing_orders.py | `return _DEFAULT_ORDERS_DIR` | `return _DEFAULT_ORDERS_DIR.parent` | T13 |
| 19 | tools.py | `with io.TextIOWrapper(io.BytesIO(snapshot.data), encoding="utf-8", newline=None) as text:` | `with io.TextIOWrapper(io.BytesIO(snapshot.data), encoding="utf-8", newline="") as text:` | T15 |
| 20 | tools.py | `except FileAccessDenied:` | `except ValueError:` | T11, T16 |
| 21 | tools.py | `+ (", ".join(names) or "none")` | `+ ", ".join(names)` | T6b |

Rows 3 and 4, and rows 2 and 5, mutate the same line in different ways; run them separately. Row 9 relies on T11's directory being inside the runtime's `data_dir` and outside its workspace exemption. Record the campaign of record in the DECISIONS entry: tree, rows killed, the first failing test per row, and the sha256 of `standing_orders.py`, `tools.py` and the test file. A later Builder whose hashes match does not repeat it.

---

## Compatibility (what a legitimate caller sees)

| Call | Before | After |
|---|---|---|
| `scope=ship` | `Standing orders not found: ship.md` | `config/standing_orders/ship.md` text |
| `scope=department`, `department` absent, `None` or `""` | not found | `engineering.md` text |
| `scope=department` or `agent`, `department="<listed name>"` | not found | that file's text |
| unknown well-formed name | not found, echoing `<name>.md` | not found, listing the available names, no echo |
| malformed name | traversal or not found | fixed refusal, no I/O |
| falsy non-string (`0`, `False`, `[]`, `{}`) | not found (fell back to `engineering`) | fixed refusal |
| vessel with `security_infra.read_roots` excluding the checkout | not found | floor/policy refusal (D6) |

No caller or test depends on the old not-found text (Absence Verified).

---

## What this does NOT change

- `_PROJECT_ROOT` in `tools.py` (`src/`), which `read_file`, `list_files` and `codebase_read_source` use for relative paths and which `tests/test_bf758_file_read_confinement.py:404-413` pins.
- The tool's schema, description, scope enum, tool id, permissions matrix (`tools.py:1322`) and the AD-1179 golden.
- `compose_instructions`, `get_order_tiers`, `_load_file` and `commands_directives.py` (which still imports `_DEFAULT_ORDERS_DIR` directly).
- The Copilot adapter's `_handle_standing_orders` (follow-up F1). `ListFilesTool` and the other F-202 readers.
- The floor itself (`security/file_access.py`), including R10's `_longest_match` (#1523 F-203).

---

## Siblings (enumerated; for follow-up, not in this slice)

| # | Site | What it does with a caller value | Same defect? |
|---|---|---|---|
| **F1** | `CopilotBuilderAdapter._handle_standing_orders`, `src/probos/cognitive/copilot_adapter.py:580-589` | `orders_path = _PROJECT_ROOT / "config" / "standing_orders" / f"{department}.md"` (`:585`), with the unchecked `department` from the visiting session's tool arguments. It echoes the value in its not-found text (`:589`) and has no floor. Registered "always" for every visiting Copilot session (`:437-449`), and approved by BF-896's permission handler (`tests/test_bf896_session_permission_handler.py:176`). Here `_PROJECT_ROOT` *is* the checkout (`:55`), so honest names work today, and so does traversal. | **Yes, exactly:** a traversal reachable by an external visiting model. **HIGH.** The fix reuses Section 1's helpers. The handler has no `runtime`, so the floor call there needs a design note (floor without runtime = platform data dir + default config files, as `file_access.py:213-239` already does). |
| F2 | `ListFilesTool.invoke`, `tools.py:528-535` | `_resolve_path(path)` passes an absolute path through (`:236-239`), and `base.glob(pattern)` runs with a caller pattern and no floor. | No. It discloses file **names** anywhere, not content; this is F-202-adjacent. Recommend adding it to the #1523 F-202 entry rather than a new issue. |
| — | `ReadFileTool` (`tools.py:439`), `CodebaseReadSourceTool` (`:745`) | They take an arbitrary path by design, through `resolve_for_runtime`. | No (floor-protected by design). |
| — | `WriteFileTool` / `EditFileTool` (`tools.py:933-963, 1014-1042`) | `_resolve_path` plus strict-root containment. | No. |
| — | `compose_instructions` / `get_order_tiers` (`standing_orders.py:146-147, 456, 461`) | They join `dept`/`agent_type` into a path. Those values come from the agent registry and `register_department` (designed agents), not from a tool parameter. | Not this defect. Whether a designed agent's `agent_type` is validated was **not enumerated**. Recorded as residual R3. |
| — | `TaskContext.get_task_orders` (`task_context.py:56`) | `f"{task_type}.md"`, where `task_type` comes from the closed `_INTENT_TASK_MAP` (`:16-30`) plus `general`. | No. |

---

## Residuals (accepted, recorded)

- **R1.** A hard link, or any process running as the vessel's user that writes into `config/standing_orders/`, can place content the tool will serve. Such a process can already write code in the checkout.
- **R2.** T9 skips on a Windows host without symlink privilege. Link refusal there rests on `read_verified_file`'s own tests (BF-758 / AD-1240).
- **R3.** The loader's own joins of `agent_type` for designed agents were not audited (see Siblings). This is low reach; consider adding a line to #1523.
- **R4.** The `department` parameter name is awkward for the `agent` scope. Changing it means a schema change (AD-1179 golden), which is a separate AD if wanted.

---

## Acceptance Criteria

1. Every value in T2/T3, in both scopes, returns the fixed refusal with no I/O and no echo. No `.md` outside the resolved base is ever passed to a reader (T18).
2. `ship`, `department` and `agent` return the real checkout files through the shipped constructor call (T13).
3. Reads go through `read_verified_file` with floor, exemption and policy (T11, T12). A link in the directory is refused (T9), and a linked directory works (T10).
4. No error text contains the caller's value or a filesystem path (T2, T6, T7, T16).
5. The existing pins listed under Tests pass unedited. The import smoke check passes.
6. All 21 mutation rows are killed, and the campaign of record is written into DECISIONS.md.
7. PROGRESS.md and DECISIONS.md are updated as in Section 4. There is no roadmap row.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-10-20, tree `5282b6e6`)

```
Read src/probos/cognitive/swe_harness/tools.py:804-860
  804: _STANDING_ORDERS_SCOPES: tuple[str, ...] = ("ship", "department", "agent")
  831:     def __init__(self, runtime: "ProbOSRuntime") -> None:
  845:         base = _PROJECT_ROOT / "config" / "standing_orders"
  851:                 target = base / "departments" / f"{dept}.md"
  854:                 target = base / "departments" / f"{dept}.md"
  856:                 return ToolResult(error=f"Standing orders not found: {target.name}")
  859:             return ToolResult(error=f"standing_orders_lookup failed: {exc}")
grep -n "_PROJECT_ROOT" src/probos/cognitive/swe_harness/tools.py
  70: _PROJECT_ROOT = Path(__file__).resolve().parents[3]
  239, 439, 534, 745, 845 (users)
Read tools.py:15-23,48-61   io, Path, typing imports; file_access imports FileAccessDenied, permitted_read_roots,
                             protected_read_roots, read_verified_file, resolve_for_runtime, workspace_exempt_roots
Read tools.py:328-332        read_verified_file(target, protected_roots=protected_read_roots(runtime), exempt_roots=..., permitted_roots=permitted_read_roots(runtime) or None)
Read tools.py:347-350        io.TextIOWrapper(io.BytesIO(snapshot.data), encoding="utf-8", newline=None) as stream
Read tools.py:1314-1322      (StandingOrdersLookupTool(runtime), read_perms)
Glob src/config/**           No files found
ls config/standing_orders    27 *.md + crew_profiles/ (no departments/)
grep -n "_DEFAULT_ORDERS_DIR" src/probos/cognitive/standing_orders.py
  35: _DEFAULT_ORDERS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "config" / "standing_orders"
Read standing_orders.py:6-10 (flat hierarchy docstring), 13-19 (import re, Path), 83-91 (register_department, set_directive_store)
Read standing_orders.py:444-463   456: dept_text = _load_file(d / f"{dept}.md")   461: agent_text = _load_file(d / f"{agent_type}.md")
grep -n "\.md\"" standing_orders.py   146: ("department", f"{dept}.md" if dept else None)   147: ("agent", f"{agent_type}.md")
Read security/file_access.py:98-155 (resolve_read_path), 158-187 (permitted_read_roots: [] by default), 190-243 (floor, runtime=None fallback),
     259-269 (resolve_for_runtime), 325-352 (validate_read_location: is_reserved, ':' refusal), 704-734 (pin_directory, read_verified_file: alias refusal at 731-732)
Read tools/protocol.py:172-199 refuse_undeclared_params
Read copilot_adapter.py:437-449, 580-589; grep "^class " -> 322: class CopilotBuilderAdapter
Read tools.py:522-535 ListFilesTool.invoke
Read tests/test_ad1179_vocabulary_constants.py:80-82,113-121; tests/test_ad544_native_tools.py:81-84,127-147
grep tests/fixtures/ad1179_tool_definition_golden.json:45 "standing_orders_lookup" schema
Read tests/test_bf758_file_read_confinement.py:26-35,140-155; tests/test_ad1200_instruction_file_access.py:36-49
grep tests/test_standing_orders_layout.py:144 RETIRED, :151 _SCANNED_TREES = (".github", "scripts", "src", "tests")
Read crew_profile.py imports: 25 and 40 are indented (TYPE_CHECKING / function-local)
grep roadmap.md:1131-1134 "## Bug Tracker" -> GitHub issues link, no table
Read DECISIONS.md:381-396 (BF-908 entry; Reversal at 396)
```

## Absence Verified (2026-10-20)

```
CLAIM: a departments/ directory never existed under config/standing_orders in any ref
RUN:   git log --all --oneline -- config/standing_orders/departments
FOUND: (no output)
HOLDS: yes

CLAIM: the tool's base directory does not exist (so every scope answered "not found")
RUN:   Glob src/config/**
FOUND: No files found
HOLDS: yes

CLAIM: no code or test depends on the old not-found / failure texts
RUN:   Grep "Standing orders not found|standing_orders_lookup failed" (whole tree)
FOUND: tools.py:856, tools.py:859 only
HOLDS: yes

CLAIM: no test invokes StandingOrdersLookupTool with a department value
RUN:   Grep "standing_orders_lookup|StandingOrdersLookupTool" (whole tree)
FOUND: test_ad544 (metadata, registry count), test_ad1179_* (schema, golden, scope refusal), test_bf896_* (name only, Copilot permission), test_copilot_adapter.py:209 (adapter tool list)
HOLDS: yes: none passes `department` to this tool

CLAIM: the mutated lines are unique in tools.py after the change
RUN:   Grep 'protected_read_roots\(self\._runtime\)|permitted_read_roots\(self\._runtime\)|if name not in names|name = "engineering"|if scope != "ship"|except FileAccessDenied:|as text:' tools.py
FOUND: No matches (before the change); tools.py:349 uses `as stream:`, so row 19's `as text:` is unique
HOLDS: yes

CLAIM: BF-910 is free and allocated to #1608
RUN:   git log --all --format=%s --grep="BF-91[0-9]" ; gh issue list --state all --search "BF-910 in:title" ; Glob prompts/bf-91*.md
FOUND: no commit; issue #1608 (OPEN) "BF-910: standing_orders_lookup reads any .md file ..."; no prompt
HOLDS: yes. AD ceiling (scripts/ad_ceiling.py): AD-1346, not used here
```

## Prior Art and Blind Spots

- **Internal.** BF-758 (`security/file_access.py`): the floor/exemption/policy split and `read_verified_file` (AD-1200/AD-1240 pinned reads). **Adopted** as the read path (D6): this repository already settled the TOCTOU, reparse-point and device-name handling there. BF-908 R9/F-202 named this tool. **Adopted:** this closes its entry. The AD-1179 vocabulary doctrine (an error, not a confident wrong answer). **Adopted** for D3/D7.
- **External.** [CWE-22](https://cwe.mitre.org/data/definitions/22.html): canonicalise then check containment, prefer mapping input to known names, and reject rather than strip. **Adopted:** D2 is an allowlist shape plus an indirect map to listed names; D6 handles canonicalisation and links. `docs/research/reference-projects.md` was not reviewed: this is a bug fix of a well-known class, not a design AD (considered, skipped).
- **Blind spots the issue does not name:** (1) the tool never worked (Problem §2); (2) Windows device names (`CON.md` can block on the console) pass a pure regex, which the listing closes; (3) case-insensitive Windows lookups, which the listing makes deterministic; (4) the failure path's `{exc}` echoed a path; (5) the Copilot adapter's twin (F1), which is reachable by an external model; (6) `_PROJECT_ROOT` in `tools.py` is `src/`, which any future `config/` reader there must not reuse.

## Amendment A1 (2026-10-20, after the sibling check)

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-20

### What A1 replaces
- **Header.** **Files** adds `src/probos/cognitive/copilot_adapter.py` and `tests/test_copilot_adapter.py`. **Estimated tests** becomes "1 new file, about 95 cases once parametrised; 1 existing test changes its patch target (`tests/test_copilot_adapter.py:286-296`)".
- **Siblings F1, What This Does NOT Change (line 414), DECISIONS residual:** F1 is now in scope. The F1 row's claim that "the handler has no `runtime`" is wrong: `CopilotBuilderAdapter.__init__` takes `runtime` (`copilot_adapter.py:337,344`). It is `None` on the dispatcher route (`build_dispatcher.py:193-197`) and set on the BuilderAgent route (`builder.py:2435-2440`).
- **Problem §3 (new):** `CopilotBuilderAdapter._handle_standing_orders` (`copilot_adapter.py:580-589`) joins the visiting session's `department` into `_PROJECT_ROOT / "config" / "standing_orders" / f"{department}.md"`. That root is the checkout (`:55`). It reads the file with no validation and no floor, and echoes the value (`:589`). It is registered under the same tool name, `standing_orders_lookup` (`:437-449`). It is reachable only when the Copilot SDK imports (`:36-42,432-433`; `build_dispatcher.py:177`; `builder.py:1243`). The `visiting_officers` config gates an unrelated registry (`startup/finalize.py:4925`).

### Decisions

| # | Decision | Reason / evidence |
|---|---|---|
| **D11** | The adapter applies D2's rule: the value must pass `is_standing_order_name` and be an exact member of `standing_order_names(resolved base)`. | Same defect, same owner of the layout (D9). |
| **D12** | The base is `standing_orders_dir()` unless the new keyword `orders_dir: Path \| None = None` is set; it is resolved once per call. `_PROJECT_ROOT` keeps its other user, the client cwd (`:350`). The three construction sites are unchanged (`build_dispatcher.py:193`, `builder.py:2435`, `commands_llm.py:110`). | One layout owner (D5), and constructor injection for tests. In a checkout, `standing_orders_dir()` and the old `_PROJECT_ROOT/"config"/"standing_orders"` are the same directory. |
| **D13** | The read is `read_verified_file(..., protected_roots=protected_read_roots(self._runtime), exempt_roots=workspace_exempt_roots(self._runtime), permitted_roots=permitted_read_roots(self._runtime) or None)`. | Same as D6. With `runtime=None` (dispatcher route) this is the platform data-dir floor plus the config files, with no policy (`file_access.py:166-169,199,231-239`). |
| **D14** | A falsy value (absent, `None`, `""`, `0`, `False`, `[]`, `{}`) still returns `No department specified`. The adapter has no default and its schema requires `department` (`:446`). A truthy non-`str` value, or a `str` subclass, gets the fixed refusal. | Keeps the old behaviour for empty input. No falsy value can name a path. |
| **D15** | Replies are fixed texts that never echo the value or a path. Not-found is `No standing orders found for that department; available: <names>`. Decoding keeps `read_text(encoding="utf-8", errors="replace")` output: `io.TextIOWrapper(..., errors="replace", newline=None)`. The texts are local to the adapter, which does not import from `swe_harness.tools`. None of them contains `.` (A1 relies on this). | Same as D7 and D8. |

### Section 5 (source): `src/probos/cognitive/copilot_adapter.py`

5a: imports. Each SEARCH below was checked with Grep and occurs once (`:14`, `:24`, `:54`, `:341-343`, `:580-589`).
```
<<<<<<< SEARCH
import asyncio
import json
import logging
=======
import asyncio
import io
import json
import logging
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
from probos.cognitive.builder_paths import builder_write_refusal
from probos.repository_instructions import (
=======
from probos.cognitive.builder_paths import builder_write_refusal
from probos.cognitive.standing_orders import (
    is_standing_order_name,
    standing_order_names,
    standing_orders_dir,
)
from probos.security.file_access import (
    FileAccessDenied,
    permitted_read_roots,
    protected_read_roots,
    read_verified_file,
    workspace_exempt_roots,
)
from probos.repository_instructions import (
>>>>>>> REPLACE
```
5b: fixed texts.
```
<<<<<<< SEARCH
logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
=======
logger = logging.getLogger(__name__)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# BF-910: fixed replies for the visiting session's standing_orders_lookup; none
# echoes the caller's value or a path, and none contains a dot.
_STANDING_ORDERS_NAME_REFUSAL = (
    "department must name one standing-orders file: 1 to 64 ASCII letters, "
    "digits, '_' or '-', for example 'engineering'"
)
_STANDING_ORDERS_DENIED = (
    "standing_orders_lookup: that standing-orders file is not readable on this vessel"
)
>>>>>>> REPLACE
```
5c: constructor.
```
<<<<<<< SEARCH
        instruction_work_dir: str | None = None,
    ) -> None:
        self._codebase_index = codebase_index
=======
        instruction_work_dir: str | None = None,
        orders_dir: Path | None = None,
    ) -> None:
        self._codebase_index = codebase_index
        # BF-910: None reads the loader's standing-orders directory at each call; tests inject one.
        self._orders_dir = orders_dir
>>>>>>> REPLACE
```
5d: handler.
```
<<<<<<< SEARCH
    async def _handle_standing_orders(self, invocation: Any) -> Any:
        args = getattr(invocation, "arguments", None) or {}
        department = args.get("department", "") if isinstance(args, dict) else ""
        if not department:
            return ToolResult(text_result_for_llm="No department specified")
        orders_path = _PROJECT_ROOT / "config" / "standing_orders" / f"{department}.md"
        if orders_path.is_file():
            content = orders_path.read_text(encoding="utf-8", errors="replace")
            return ToolResult(text_result_for_llm=content)
        return ToolResult(text_result_for_llm=f"No standing orders found for department: {department}")
=======
    async def _handle_standing_orders(self, invocation: Any) -> Any:
        args = getattr(invocation, "arguments", None) or {}
        department = args.get("department", "") if isinstance(args, dict) else ""
        if not department:
            return ToolResult(text_result_for_llm="No department specified")
        # BF-910: a name from the loader's flat directory, never a path.
        if not is_standing_order_name(department):
            return ToolResult(text_result_for_llm=_STANDING_ORDERS_NAME_REFUSAL)
        try:
            base = (self._orders_dir or standing_orders_dir()).resolve()
            names = standing_order_names(base)
            if department not in names:
                return ToolResult(
                    text_result_for_llm="No standing orders found for that department; available: "
                    + (", ".join(names) or "none")
                )
            # BF-910: the BF-758 floor, the operator's read policy and a pinned,
            # link-refusing read. runtime None (dispatcher route) is the
            # platform-data-dir floor with no policy.
            snapshot = read_verified_file(
                base / f"{department}.md",
                protected_roots=protected_read_roots(self._runtime),
                exempt_roots=workspace_exempt_roots(self._runtime),
                permitted_roots=permitted_read_roots(self._runtime) or None,
            )
            # Path.read_text(encoding="utf-8", errors="replace")'s output, as before.
            with io.TextIOWrapper(
                io.BytesIO(snapshot.data), encoding="utf-8", errors="replace", newline=None,
            ) as text:
                return ToolResult(text_result_for_llm=text.read())
        except FileAccessDenied:
            return ToolResult(text_result_for_llm=_STANDING_ORDERS_DENIED)
        except Exception as exc:
            logger.warning("BF-910: visiting standing_orders_lookup read failed: %s", type(exc).__name__)
            return ToolResult(text_result_for_llm=f"standing_orders_lookup failed: {type(exc).__name__}")
>>>>>>> REPLACE
```
Import safety: `security/file_access.py` has no module-level `probos` import (`:36-48`), and `standing_orders.py` imports only `probos.crew_profile` (`:21`), whose module-level imports are stdlib (`crew_profile.py:11-22`). No cycle.

### Section 6 (tests first): changing an existing test, `tests/test_copilot_adapter.py`

The test used to patch `_PROJECT_ROOT`. The handler no longer reads it, so the test injects the directory instead. The assertion is unchanged.
```
<<<<<<< SEARCH
            adapter = CopilotBuilderAdapter()
            # Patch the project root to use our temp dir
            with patch("probos.cognitive.copilot_adapter._PROJECT_ROOT", Path(tmpdir)):
                result = await adapter._handle_standing_orders(_make_invocation(department="engineering"))
            assert "Build well" in result.text_result_for_llm
=======
            # BF-910: the handler reads standing_orders_dir() (the loader's directory),
            # not _PROJECT_ROOT, so the directory is injected rather than patched.
            adapter = CopilotBuilderAdapter(orders_dir=orders_dir)
            result = await adapter._handle_standing_orders(_make_invocation(department="engineering"))
            assert "Build well" in result.text_result_for_llm
>>>>>>> REPLACE
```
(`patch` is still used elsewhere in that file, at `:41`.)

### Tests (written first): new cases in `tests/test_bf910_standing_orders_lookup.py`

**How they are driven:**
- Build `CopilotBuilderAdapter(runtime=_runtime(tmp_path), orders_dir=orders)` and call `await adapter._handle_standing_orders(SimpleNamespace(arguments={...}))`, then read `.text_result_for_llm`.
- Neither the SDK nor the network is needed. The module's fallback `ToolResult` (`copilot_adapter.py:44-46`) serves when the SDK is absent, and `start()` is never called.
- Spy on `probos.cognitive.copilot_adapter.read_verified_file`, which the module imports by name, in the same way as `reads`.

**Shared assertions:**
- "no reads" means the spy saw no `read_verified_file` call and no `.md` path went through `Path.read_text`.
- "not echoed" means the value does not appear in the reply.

| # | Name | Proves |
|---|---|---|
| T21 | `test_adapter_refuses_a_name_that_is_not_one_segment[value]` (T2's non-empty values) | Reply `== copilot_adapter._STANDING_ORDERS_NAME_REFUSAL`, not echoed, no marker text, no reads. |
| T22 | `test_adapter_refuses_a_truthy_non_string[value]`: `5`, `1.5`, `True`, `["engineering"]`, `{"a":1}`, `b"engineering"`, `_Str("engineering")` | Same refusal, no reads (D14). |
| T23 | `test_adapter_falsy_department_is_unspecified[value]`: absent, `None`, `""`, `0`, `False`, `[]`, `{}` | Reply `== "No department specified"`, no reads (D14, unchanged). |
| T24 | `test_adapter_real_names_resolve`: `engineering`, `builder`, `ship` | The file text; exactly one verified read, at `orders.resolve()/"<name>.md"`. |
| T25 | `test_adapter_unknown_case_and_device_names_are_not_found`: `nosuch`, `crew_profiles`, `Engineering`, `CON`, `NUL`, `COM1` | Reply `== "No standing orders found for that department; available: builder, engineering, science, ship"`, not echoed, no reads. |
| T26 | `test_adapter_missing_directory_has_no_names` (`orders_dir=tmp_path/"absent"`) | Reply ends with `available: none`. |
| T27 | `test_adapter_link_in_directory_is_refused` (as T9; skip on `OSError`/`NotImplementedError`) | Reply `== _STANDING_ORDERS_DENIED`, and `MARKER-BF910-ROOT` is absent. |
| T28 | `test_adapter_linked_directory_is_read_through_its_resolution` (as T10) | ENG. |
| T29 | `test_adapter_floor_refuses_data_dir` (as T11) | Denied, and ENG is absent. |
| T30 | `test_adapter_operator_read_policy_applies` (as T12) | Denied, then ENG. |
| T31 | `test_adapter_read_failure_names_only_its_type` (as T16) | Exactly `standing_orders_lookup failed: PermissionError`, then the denied text; `str(tmp_path)` in neither. |
| T32 | `test_adapter_output_parity` (`b"A\r\nB\r\n"` gives `"A\nB\n"`; `b"A\xff"` gives `"A\ufffd"`) | D15. |
| T33 | `test_adapter_shipped_construction_reads_the_loaders_directory` (`CopilotBuilderAdapter()`, the dispatcher's shape with no runtime and no `orders_dir`) | `engineering` returns exactly `(standing_orders_dir()/"engineering.md").read_text(encoding="utf-8", errors="replace")`. |
| T34 | `test_adapter_every_read_stays_in_the_base` (T21-T25 inputs in one loop) | Every verified path's parent is `orders.resolve()`. |

### Mutation table delta (file `copilot_adapter.py`; each line is unique in it after the change)

| # | Line (stripped) | Mutant | Killed by |
|---|---|---|---|
| 22 | `if not is_standing_order_name(department):` | `if False:` | T21 |
| 23 | `if department not in names:` | `if False:` | T25 |
| 24 | `base = (self._orders_dir or standing_orders_dir()).resolve()` | `base = self._orders_dir or standing_orders_dir()` | T28 |
| 25 | `protected_roots=protected_read_roots(self._runtime),` | `protected_roots=[],` | T29 |
| 26 | `permitted_roots=permitted_read_roots(self._runtime) or None,` | `permitted_roots=None,` | T30 |
| 27 | `return ToolResult(text_result_for_llm=f"standing_orders_lookup failed: {type(exc).__name__}")` | `...{exc}")` | T31 |
| 28 | `io.BytesIO(snapshot.data), encoding="utf-8", errors="replace", newline=None,` | `newline="",` | T32 |
| 29 | same line | `errors="strict"` | T32 |
| 30 | `except FileAccessDenied:` | `except ValueError:` | T27, T29 |
| 31 | `+ (", ".join(names) or "none")` | `+ ", ".join(names)` | T26 |

- Rows 28 and 29 mutate the same line; run them separately.
- The mutant `_PROJECT_ROOT / "config" / "standing_orders"` in place of `standing_orders_dir()` is **equivalent** in a checkout (same directory), so it is not run.
- The campaign of record adds `copilot_adapter.py`'s sha256.

### Milestones
- **M3 (new): adapter.** Sections 5-6 and T21-T34. Focused check:
  - `tests/test_bf910_standing_orders_lookup.py -k adapter tests/test_copilot_adapter.py tests/test_bf896_session_permission_handler.py tests/test_bf896_dispatcher_confinement_seam.py -n 0 -q`
  - Import smoke: `d:/ProbOS/.venv/Scripts/python.exe -c "import probos.cognitive.copilot_adapter, probos.build_dispatcher, probos.cognitive.builder"`
- **The old M3 becomes M4.** It runs 31 rows, and its retired-name scan covers the edited `tests/test_copilot_adapter.py`.

### Trackers
- **PROGRESS.md:** replace the paragraph's last sentence with: "The Copilot visiting-session handler registered under the same tool name (`CopilotBuilderAdapter._handle_standing_orders`), which joined the value into a path from the checkout root, now follows the same name rule and makes the same verified read; it is reachable only when the optional Copilot SDK is installed."
- **DECISIONS.md BF-910 entry:** insert before `*Residual.*`: "- *A1 (D11-D15, the sibling).* `copilot_adapter._handle_standing_orders` has the same name rule and verified read, with `runtime=None` on the dispatcher route giving the platform floor without policy; a falsy value still answers 'No department specified'; replies never echo." In `*Residual.*`, delete the sentence about the Copilot adapter.
- **Acceptance criteria:** add "9. T21-T34 pass; rows 22-31 are killed; `tests/test_copilot_adapter.py::test_handle_standing_orders` passes with the injected directory."

**Absence verified (A1):** a Grep of the tree outside `prompts/` for `No department specified|No standing orders found|standing_orders_dir|is_standing_order_name` finds `copilot_adapter.py:584,589` only. A Grep for `_handle_standing_orders` in tests finds only `test_copilot_adapter.py:295`. No test depends on the old reply texts.

## Amendment A2 (2026-10-20, after the M3 architecture-check hard stop)

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-20

### What A2 replaces
- **Header, Files:** add `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`, both regenerated rather than hand-edited (D19). `docs/development/architecture-baseline.yaml` is **not** in the change.
- **Mutation table delta (A1):** rows 24-26 get new anchors. Rows 32-35 are added. The "equivalent mutant" note is deleted, because it is now row 35.

### Decisions
D16-D19 as above.

### Section 7 (source): `src/probos/cognitive/copilot_adapter.py`, written against the candidate

7a: the module-level reply. Its SEARCH occurs once (`:76-78`).
```
<<<<<<< SEARCH
_STANDING_ORDERS_DENIED = (
    "standing_orders_lookup: that standing-orders file is not readable on this vessel"
)
=======
_STANDING_ORDERS_DENIED = (
    "standing_orders_lookup: that standing-orders file is not readable on this vessel"
)


def _standing_orders_reply(
    invocation: Any, orders_dir: Path | None, runtime: ProbOSRuntime | None
) -> Any:
    """BF-910: the reply to the visiting session's ``standing_orders_lookup``.

    ``CopilotBuilderAdapter._handle_standing_orders`` is the registered handler and
    passes its ``orders_dir`` and ``runtime``. The body sits outside the class so the
    class stays under the repository's 500-line SRP review trigger (BF-910 D16).
    """
    args = getattr(invocation, "arguments", None) or {}
    department = args.get("department", "") if isinstance(args, dict) else ""
    if not department:
        return ToolResult(text_result_for_llm="No department specified")
    # BF-910: a name from the loader's flat directory, never a path.
    if not is_standing_order_name(department):
        return ToolResult(text_result_for_llm=_STANDING_ORDERS_NAME_REFUSAL)
    try:
        base = (orders_dir or standing_orders_dir()).resolve()
        names = standing_order_names(base)
        if department not in names:
            return ToolResult(
                text_result_for_llm="No standing orders found for that department; available: "
                + (", ".join(names) or "none")
            )
        # BF-910: the BF-758 floor, the operator's read policy and a pinned,
        # link-refusing read. runtime None (dispatcher route) is the
        # platform-data-dir floor with no policy.
        snapshot = read_verified_file(
            base / f"{department}.md",
            protected_roots=protected_read_roots(runtime),
            exempt_roots=workspace_exempt_roots(runtime),
            permitted_roots=permitted_read_roots(runtime) or None,
        )
        # Path.read_text(encoding="utf-8", errors="replace")'s output, as before.
        with io.TextIOWrapper(
            io.BytesIO(snapshot.data), encoding="utf-8", errors="replace", newline=None,
        ) as text:
            return ToolResult(text_result_for_llm=text.read())
    except FileAccessDenied:
        return ToolResult(text_result_for_llm=_STANDING_ORDERS_DENIED)
    except Exception as exc:
        logger.warning("BF-910: visiting standing_orders_lookup read failed: %s", type(exc).__name__)
        return ToolResult(text_result_for_llm=f"standing_orders_lookup failed: {type(exc).__name__}")
>>>>>>> REPLACE
```
**Why the names resolve:**
- `ToolResult` is bound at module scope before this point, at `:51` or by the fallback at `:57`.
- `logger` is bound at `:67`.
- `ProbOSRuntime` is a `TYPE_CHECKING` import (`:47`). Annotations are strings under `from __future__ import annotations` (`:12`).

7b: the handler becomes the delegate. Its SEARCH is `:606-640` and occurs once.
```
<<<<<<< SEARCH
    async def _handle_standing_orders(self, invocation: Any) -> Any:
        args = getattr(invocation, "arguments", None) or {}
        department = args.get("department", "") if isinstance(args, dict) else ""
        if not department:
            return ToolResult(text_result_for_llm="No department specified")
        # BF-910: a name from the loader's flat directory, never a path.
        if not is_standing_order_name(department):
            return ToolResult(text_result_for_llm=_STANDING_ORDERS_NAME_REFUSAL)
        try:
            base = (self._orders_dir or standing_orders_dir()).resolve()
            names = standing_order_names(base)
            if department not in names:
                return ToolResult(
                    text_result_for_llm="No standing orders found for that department; available: "
                    + (", ".join(names) or "none")
                )
            # BF-910: the BF-758 floor, the operator's read policy and a pinned,
            # link-refusing read. runtime None (dispatcher route) is the
            # platform-data-dir floor with no policy.
            snapshot = read_verified_file(
                base / f"{department}.md",
                protected_roots=protected_read_roots(self._runtime),
                exempt_roots=workspace_exempt_roots(self._runtime),
                permitted_roots=permitted_read_roots(self._runtime) or None,
            )
            # Path.read_text(encoding="utf-8", errors="replace")'s output, as before.
            with io.TextIOWrapper(
                io.BytesIO(snapshot.data), encoding="utf-8", errors="replace", newline=None,
            ) as text:
                return ToolResult(text_result_for_llm=text.read())
        except FileAccessDenied:
            return ToolResult(text_result_for_llm=_STANDING_ORDERS_DENIED)
        except Exception as exc:
            logger.warning("BF-910: visiting standing_orders_lookup read failed: %s", type(exc).__name__)
            return ToolResult(text_result_for_llm=f"standing_orders_lookup failed: {type(exc).__name__}")
=======
    async def _handle_standing_orders(self, invocation: Any) -> Any:
        # BF-910 (D16): the registered handler; the reply is _standing_orders_reply's.
        return _standing_orders_reply(invocation, self._orders_dir, self._runtime)
>>>>>>> REPLACE
```

### Section 8 (tests): `tests/test_bf910_standing_orders_lookup.py`, written against the candidate

T21-T34 stay as they are, apart from T33's setup (8e). T35 is new (8f).

8a (docstring, `:13-14`):
```
<<<<<<< SEARCH
session's ``standing_orders_lookup``; its tests, T21 to T34, are in this file as
well.
=======
session's ``standing_orders_lookup``; its tests, T21 to T35, are in this file as
well.
>>>>>>> REPLACE
```
8b (`:18-19`):
```
<<<<<<< SEARCH
Tests section and T21 to T34 in its Amendment A1. T19b is a row added to the
first of them, for the order of the names.
=======
Tests section, T21 to T34 in its Amendment A1 and T35 in its Amendment A2. T19b
is a row added to the first of them, for the order of the names.
>>>>>>> REPLACE
```
8c (`:85-90`):
```
<<<<<<< SEARCH
- Built with neither ``runtime`` nor ``orders_dir`` (the platform data directory
  that the floor then falls back to is pointed into ``tmp_path``), the handler
  returns the ``engineering`` file of the loader's directory, the checkout's
  tracked ``config/standing_orders/`` (T33).
- Across the inputs of T21 to T25, every verified read is of a file directly in
  the base, and no ``.md`` file is read with ``Path.read_text`` (T34).
=======
- Built with neither ``runtime`` nor ``orders_dir`` (the platform data directory
  that the floor then falls back to is pointed into ``tmp_path``), the handler
  returns the ``engineering`` file of the loader's directory, the checkout's
  tracked ``config/standing_orders/``, and not the file of a decoy tree that
  ``_PROJECT_ROOT`` is pointed at for the test (T33).
- Across the inputs of T21 to T25, every verified read is of a file directly in
  the base, and no ``.md`` file is read with ``Path.read_text`` (T34).
- The handler that ``_build_mcp_tools`` registers under the name
  ``standing_orders_lookup`` refuses a path with the fixed text and returns a
  listed name's file (T35); a recorder stands in for the SDK's ``Tool``.
>>>>>>> REPLACE
```
8d (`:117-130`):
```
<<<<<<< SEARCH
- The Copilot session around the handler. T21 to T34 call
  ``_handle_standing_orders`` directly, with a ``SimpleNamespace`` in the place
  of the SDK's tool invocation: they do not start the SDK, a client or a
  session, and they use no network. That the handler is registered as the
  session's ``standing_orders_lookup``, and what a session sends it, are not
  exercised here.
=======
- The Copilot session around the handler. T21 to T34 call
  ``_handle_standing_orders`` directly, and T35 calls the handler that
  ``_build_mcp_tools`` registers, with a ``SimpleNamespace`` in the place of the
  SDK's tool invocation and a recorder in the place of the SDK's ``Tool``: they
  do not start the SDK, a client or a session, and they use no network. What a
  session sends the handler is not exercised here.
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
- That the handler no longer reads the checkout root for its default directory:
  in a checkout, ``standing_orders_dir()`` and the
  ``_PROJECT_ROOT/config/standing_orders`` it used to read are the same
  directory, so T33 cannot tell them apart.
=======
- That the handler reads no checkout root other than through ``_PROJECT_ROOT``:
  T33 points ``_PROJECT_ROOT`` at a decoy, which tells the loader's directory
  from the one the handler used to read, but a handler that computed the
  checkout root afresh would, in a checkout, read the loader's directory.
>>>>>>> REPLACE
```
8e (T33's setup, `:1001-1005`):
```
<<<<<<< SEARCH
    # With no runtime the floor falls back to the platform data directory: point it into tmp_path,
    # so that no live data directory is consulted.
    monkeypatch.setenv("PROBOS_DATA_DIR", str(tmp_path / "data"))
    expected = (standing_orders_dir() / "engineering.md").read_text(encoding="utf-8", errors="replace")
    assert expected
=======
    # With no runtime the floor falls back to the platform data directory: point it into tmp_path,
    # so that no live data directory is consulted.
    monkeypatch.setenv("PROBOS_DATA_DIR", str(tmp_path / "data"))
    # A decoy checkout root whose config/standing_orders holds other text: a handler that read
    # _PROJECT_ROOT's directory rather than the loader's would answer with the decoy (row 35).
    decoy_marker = "MARKER-BF910-DECOY"
    decoy_orders = tmp_path / "decoy" / "config" / "standing_orders"
    decoy_orders.mkdir(parents=True)
    (decoy_orders / "engineering.md").write_text(decoy_marker, encoding="utf-8")
    monkeypatch.setattr(copilot_adapter, "_PROJECT_ROOT", tmp_path / "decoy")
    expected = (standing_orders_dir() / "engineering.md").read_text(encoding="utf-8", errors="replace")
    assert expected
    assert decoy_marker not in expected
>>>>>>> REPLACE
```
8f (T35, appended after T34's last three lines, `:1034-1036`; the first line occurs once, and `:739` reads `assert reads.verified`):
```
<<<<<<< SEARCH
    assert adapter_reads.verified, "no verified read happened, so the check below would prove nothing"
    assert all(path.parent == orders.resolve() for path in adapter_reads.verified)
    assert adapter_reads.plain_markdown == []
=======
    assert adapter_reads.verified, "no verified read happened, so the check below would prove nothing"
    assert all(path.parent == orders.resolve() for path in adapter_reads.verified)
    assert adapter_reads.plain_markdown == []


@pytest.mark.asyncio
async def test_adapter_registered_handler_is_the_guarded_one(
    tmp_path: Path, orders: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T35: the handler ``_build_mcp_tools`` registers as ``standing_orders_lookup`` is the guarded one.

    Crosses registration to handler: the callable the visiting session is given
    refuses a path with the fixed text and returns a listed name's file.
    """
    registered: list[dict[str, Any]] = []

    def tool(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert not args, "the adapter registers its tools by keyword"
        registered.append(kwargs)
        return kwargs

    monkeypatch.setattr(copilot_adapter, "_SDK_AVAILABLE", True)
    monkeypatch.setattr(copilot_adapter, "Tool", tool, raising=False)
    adapter = _adapter(tmp_path, orders)

    adapter._build_mcp_tools()
    handlers = [kwargs["handler"] for kwargs in registered if kwargs.get("name") == "standing_orders_lookup"]
    assert len(handlers) == 1
    handler = handlers[0]

    refused = await handler(SimpleNamespace(arguments={"department": "../secret"}))
    found = await handler(SimpleNamespace(arguments={"department": "engineering"}))

    assert refused.text_result_for_llm == copilot_adapter._STANDING_ORDERS_NAME_REFUSAL
    assert found.text_result_for_llm == _ENG
>>>>>>> REPLACE
```
**Why T35 works without the SDK:**
- `_build_mcp_tools` uses only `_SDK_AVAILABLE` and `Tool` (`:458-554`).
- Each of its `Tool(...)` calls is keyword-only (`:464-475`, `:547-552`).
- With `runtime` set, it also registers `system_self_model`, without calling the runtime.

### Mutation table (file `copilot_adapter.py`, after A2): rows 22-35
| # | Line (stripped) | Mutant | Killed by |
|---|---|---|---|
| 22 | `if not is_standing_order_name(department):` | `if False:` | T21 |
| 23 | `if department not in names:` | `if False:` | T25 |
| 24 | `base = (orders_dir or standing_orders_dir()).resolve()` | `base = orders_dir or standing_orders_dir()` | T28 |
| 25 | `protected_roots=protected_read_roots(runtime),` | `protected_roots=[],` | T29 |
| 26 | `permitted_roots=permitted_read_roots(runtime) or None,` | `permitted_roots=None,` | T30 |
| 27 | `return ToolResult(text_result_for_llm=f"standing_orders_lookup failed: {type(exc).__name__}")` | `...{exc}")` | T31 |
| 28 | `io.BytesIO(snapshot.data), encoding="utf-8", errors="replace", newline=None,` | `newline="",` | T32 |
| 29 | same line | `errors="strict"` | T32 |
| 30 | `except FileAccessDenied:` | `except ValueError:` | T27, T29 |
| 31 | `+ (", ".join(names) or "none")` | `+ ", ".join(names)` | T26 |
| 32 | `return _standing_orders_reply(invocation, self._orders_dir, self._runtime)` | `(invocation, None, self._runtime)` | T24, T35 |
| 33 | same line | `(invocation, self._orders_dir, None)` | T30 |
| 34 | `handler=self._handle_standing_orders,` | `handler=self._handle_find_callers,` | T35 |
| 35 | row 24's line | `base = (orders_dir or _PROJECT_ROOT / "config" / "standing_orders").resolve()` | T33 |

**Running the rows:**
- Rows that share a line run separately: 28 and 29, 32 and 33, 24 and 35.
- Rows 1-21 are in `standing_orders.py` and `tools.py`, which A2 does not touch. If the campaign of record's sha256 for those two files still matches, they are not rerun.
- Rows 22-35 are run against `copilot_adapter.py`'s new sha256.

**Uniqueness:** with 7b applied, the old `self._runtime` forms of rows 25-26 are gone. `except FileAccessDenied:` and `orders_dir or standing_orders_dir()` each have one hit in the candidate (Grep `:615`, `:636`). `handler=self._handle_standing_orders,` has one (`:474`).

### Milestone M3b (Builder)
1. Apply Sections 7 and 8.
2. Focused check: `pytest tests/test_bf910_standing_orders_lookup.py tests/test_copilot_adapter.py tests/test_bf896_session_permission_handler.py tests/test_bf896_dispatcher_confinement_seam.py -n 0 -q`.
3. Import smoke as in A1's M3.
4. Run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check`.
5. Run the span probe; it must print `491 16`: `d:/ProbOS/.venv/Scripts/python.exe -c "import ast,pathlib;t=ast.parse(pathlib.Path('src/probos/cognitive/copilot_adapter.py').read_text(encoding='utf-8'));c=[n for n in t.body if isinstance(n,ast.ClassDef) and n.name=='CopilotBuilderAdapter'][0];print(c.end_lineno-c.lineno+1, sum(isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef)) for x in c.body))"`

### Trackers (docs milestone)
**DECISIONS.md, BF-910 entry.** After the A1 bullet, insert:

"- *A2 (D16-D19).* The visiting handler's body is the module-level `copilot_adapter._standing_orders_reply(invocation, orders_dir, runtime)`. `CopilotBuilderAdapter._handle_standing_orders` stays the registered handler and passes its `orders_dir` and `runtime`. With the body in the class, the class spanned 523 lines, which crossed the 500-line SRP review trigger and failed `check_architecture_principles.py --check` as trigger drift. With the body moved out it spans 491, and its `srp-size` baseline row (`triggers: [methods]`, owner AD-1270h) is unchanged. A shared reply helper in `standing_orders.py` was rejected: the tool and the adapter differ in decoding and reply type, and the tests spy each module's own `read_verified_file`. T35 calls the handler that `_build_mcp_tools` registers. T33 points `_PROJECT_ROOT` at a decoy tree, so it tells the loader's directory from the checkout root's."

**PROGRESS.md:** no text beyond A1's sentence.

**Ledger (D19):** after editing both trackers, run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, then `... gen_ad_ledger.py --check`. Commit the regenerated `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` with the trackers.

### Acceptance criteria (added)
10. `scripts/check_architecture_principles.py --check` exits 0, and `git diff --quiet HEAD -- docs/development/architecture-baseline.yaml` exits 0. The span probe prints `491 16`.
11. T21-T35 pass. Rows 22-35 are killed, with rows 24-26 on their A2 anchors.
12. `scripts/gen_ad_ledger.py --check` exits 0 after the tracker edits. `check_seam_contracts.py`, `check_store_registry.py` and `check_config_facade.py` each exit 0 with `--check`.
