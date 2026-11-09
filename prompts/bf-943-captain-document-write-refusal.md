# BF-943 (#1707): Agents cannot rewrite the Captain's governance, instruction and manifest files in the running checkout: one rule, called by the eight agent-reachable write sites

**Drafted by:** `Architect` (GitHub Copilot fallback; the Claude Code bridge was unavailable), 2026-11-09
**Status:** ready to build on `origin/main` `bab8413e` (BF-942 merged, #1778). Read at `63cf49cc` (`0c4e43c5` plus BF-942's six commits) in the reading tree `D:\ProbOS-worktrees\bf942-build`, which was removed during the final pass; the last checks used `git show` in `D:\ProbOS`, and at `63cf49cc` and at `bab8413e` the eight blobs below are identical and every pair of M1 to M3 applies, each SEARCH once at its turn. **Oracle:** no test run (a read-only consult; a gate was running). An in-memory script applied the 14 pairs of M2, the 4 repairs of M1, the 3 tracker pairs and the new test file to the LF blobs (each SEARCH once, every result compiles), overlaid the patched modules on the tree and drove the test functions by hand, no pytest runner (section 11). Base: the 21 guards pass and the 464 class cases fail at their own `assert`; M2's head: all 485 pass; AD-1344's file (147 cases): 143 pass and 4 fail without N1-2 to N1-5, and all pass with them on both trees; BF-911's 119 pass on both; the mutants of section 9 fail the cases listed. G1 to G3 and the gate's preflight were not run.
**Base blobs (`63cf49cc` and `bab8413e`):** `builder_paths.py` `d43190b838bf`, `swe_harness/tools.py` `23dbf87f71d3`, `agents/file_writer.py` `f1b0a7c009fd`, `skill_framework.py` `2063f62c7944`, `tests/test_ad1344_constitution_write_refusal.py` `e6a989f70a28`, `PROGRESS.md` `ba480cd89482`, `DECISIONS.md` `688d642b382a`, `docs/development/deterministic-ship.md` `7e8f0d650032`.
**Dependencies:** BF-942, merged (only P3-1 and P3-2 are anchored on its text; no code SEARCH is in a file its commits touch). **Tier:** M1 STANDARD (tests); M2 HIGH (a security control); M3 STANDARD. **Estimated tests:** one new file, 485 cases (21 pass, 464 xfail at M1); four AD-1344 cases repaired. **BF number:** BF-943, held by #1707 (open, `bug`); nothing new is allocated; the one commit that names it, `1edb960d`, is a documents-only research note (section 11).

**Which text describes the head.** Before building: `git rev-parse HEAD:<path>` for the eight paths prints the blobs above, `git diff --stat 0c4e43c5 HEAD -- src tests` lists only BF-942's `event_log.py` and test, and the new file does not exist. A SEARCH that does not occur exactly once is a hard stop for the Architect. Working copies are CRLF and SEARCH text is LF; where prose and a block differ, the block wins. Apply the pairs with the `edit` tool one at a time, whole block, in label order.

## 1. Problem

**The gap.** Three rules stop agent file writes: the builder's, AD-1344's (the Constitution) and BF-911's (the loaded config, `config/system.yaml`, `~/.probos/config.yaml`, the vault's file names). The eight sites below call the last two and no other path rule, so an agent holding a write tool can rewrite, unreviewed, the other standing-orders tiers, `config/ontology/`, `config/sealed_modules.yaml`, `config/command_policy/`, `CLAUDE.md`, `.claude/`, `.github/`, the lock files and manifests, and create an `AGENTS.md` or a `CODEOWNERS` (readers and effects: the issue's table, not re-measured).

| Site (AD-1344's call; BF-911's follows) | Root it passes | A relative path lands | Refusal shape |
|---|---|---|---|
| `WriteFileTool.invoke` `swe_harness/tools.py:1065`, `EditFileTool.invoke` `:1158` | `_PROJECT_ROOT` = `<checkout>/src` | `src/<path>` | `ToolResult(error=)` |
| `FileWriterAgent.act` `agents/file_writer.py:112`, `commit_write` `:155` | `Path.cwd()` | `<cwd>/<path>` | `{"success": False, "error": }` |
| `DocxAgent.create_docx` `skill_framework.py:210`, `revise_docx` `:266`, `PptxAgent.create_pptx` `:417`, `XlsxAgent.update_xlsx` `:546` | `Path.cwd()` | `<cwd>/<path>` | `raise PermissionError` |

`git grep -n -E '(constitution_write_refusal|protected_write_refusal|builder_write_refusal)\(' 63cf49cc -- src` lists the three definitions, these eight sites (each calls AD-1344's rule, then BF-911's), `builder.py:3396` and `copilot_adapter.py:322` (the builder's rule only), and two calls inside `builder_paths.py` (`:247`, AD-1344's rule from `builder_write_refusal`; `:336`, the builder's rule from `fix_loop_write_refusal`). `commit_write` is also reached by `submit_write_with_consensus` (`runtime.py:4994`) and the todo, scheduler and note agents (`productivity_agents.py:111`, `organizer_agents.py:52`).

**What reading corrects in the issue** (enumerations: section 11).
1. *The SWE root is `<checkout>/src`.* `Path(__file__).resolve().parents[3]` of `swe_harness/tools.py:81` is `src` (computed; BF-911's tests build that layout, `test_bf911_protected_config_write_refusal.py:7-9`). A relative `config/standing_orders/ship.md` given to `write_file` lands in `src/config/standing_orders/`, which the loader does not read (`standing_orders.py:35` takes the checkout's `config/standing_orders`); the real file is reached by `../config/...` or an absolute path.
2. *The DM route reaches `invoke` (by reading; no test run).* `dm_agentic.enabled: true` ships (`config/system.yaml:469-470`). The DM turn's `WorkItemAgenticExecutor` (`cognitive_agent.py:4871`) builds `DispatchToolExecutor(registry=, effect_broker=)` (`agentic_dispatch.py:2987`), offers the Captain's grants (`:3080`) and passes no confinement (`confinement=` occurs once in `src`, `agent_work_runner.py:631`). The loop's call (`swe_harness/agentic_loop.py:2684`) passes no `required`, so `check_and_invoke` asks for READ (`tools/registry.py:368`), and the rank matrix gives `lieutenant: write` (`tools.py:1434-1439`) on a tool registered whatever the harness flag says (`startup/finalize.py:1842-1844`, `:1882`). `_invoke_reserved_body` (`agentic_dispatch.py:800-933`) refuses by confinement, plan mode, a deferred schema, a browser action and the approval inbox (`{"browser"}`, `:230`), not for an unoffered tool; the offered names are read only after the run (`cognitive/dm/reply_value.py:74-106`), and the code says the executor resolves a name outside the offer (`agentic_dispatch.py:3600-3603`; `tool_manifest.py:320-321`). What a model emits for an unoffered name was not read. **By the issue's rule the severity is High.** T4 runs the executor half and the orchestrator's executed probe confirms it before M1 is committed; if T4 fails, P3-1's `High` becomes `Medium`.
3. *AD-548's `blocked_paths` hook is not on `DispatchToolExecutor`.* It is added once, to the runtime's `tool_executor` (`finalize.py:1890`); `_pre_hooks` is per instance (`tools/executor.py:510`); the only `DispatchToolExecutor` is built per run (`agentic_dispatch.py:2987`) and only a start hook is added to it (`:3044`). No change (L6).
4. *The AD-546 native harness is a caller.* `Builder.perceive` (`builder.py:2553-2578`) passes `work_dir=str(_PROJECT_ROOT)` (the checkout) to a loop that offers `write_file` and `edit_file` (`native_builder.py:48-49`), so its in-place edits run through these tools in the running checkout. It is off by default (`config/system.yaml:903`).

**The build lane** is `execute_approved_build` (`builder.py:3396`, then writes under the BF-897 worktree; `:3301` refuses the runtime's checkout), `build_dispatcher.py`, `worktree_manager.py` and the visiting session (`copilot_adapter.py:322`). The new rule's callers are the eight sites and none is in those modules (T30); the AD-546 harness reaches two of them (item 4 above): with M2 an in-place harness edit of an entry is refused, and a `===FILE:` block in its final text still reaches the worktree (L7).

**Writers that call none.** AD-1344's census B (`test_ad1344_constitution_write_refusal.py:758-787`, over `agents/`, `tools/`, `swe_harness/`, `skill_framework.py`, `builder.py`, `copilot_adapter.py`, `skill_forge.py` and `skill_catalog.py`) classifies each other write call by its target: a store record (`http_fetch.py:964`), the avatar store (`avatar_agents.py:170`), a cataloged skill's directory and the forge's staging directory (`skill_catalog.py`, `skill_forge.py`), the credential vault and recordings (`tools/browser/*`), the run's own work directory (`tools/code_execution_tool.py:652`, `:1175`), and the build lane's restore and session directory. Its write names do not include `mkdir`: `code_runner.py:255`, `:397` and `tools/code_execution_tool.py:772`, which create a run's work directory, are not among its sites. None is widened here (the issue's Do Not Build); the shell, `run_python`, MCP servers and agent-designed code are #1523's residuals (`DECISIONS.md:465`, `:479`).

## 2. Solution

`builder_paths.py` gains `CAPTAIN_DOCUMENT_PATHS` (17 entries) and `captain_document_write_refusal(path, root=None) -> str | None`, which judges a path against the running checkout (the directory above `constitution_path()`) and the writer's root, as written and as resolved, and refuses an existing file that is a second name of an existing document. The eight sites call it after AD-1344's call with that site's arguments, error shape and a constant log line. A sibling census in the new test file fails a writer that calls one rule and not the other. Four AD-1344 tests whose controls wrote under the set move to a neighbour.

## 3. Decisions

**D1. The set and its matching.**

| # | Option | Judgement |
|---|---|---|
| 1 | The issue's 17 entries in one tuple; components in BF-894's canonical form; a trailing `/` names a directory and all below it; `*` globs within one component (`requirements*.txt`, root only); an 8.3 short form accepted per component; `.github/CODEOWNERS` is under `.github/`; an absent name is named (chosen) | The issue's list binds; one declaration. `git ls-tree` at HEAD: present `CLAUDE.md`, `pyproject.toml`, `uv.lock`, `ui/package.json`, `ui/package-lock.json`, `config/sealed_modules.yaml`, `config/command_policy/` (1 file), `config/ontology/` (9), `config/standing_orders/` (43), `.claude/` (3), `.github/` (5); absent `AGENTS.md`, `.agents/`, `.codex/`, `requirements*.txt`, CODEOWNERS in all three places |
| 2 | Also the same-class files that exist (L3) | Wider cover; beyond the Fix list and a product call; one line later |
| 3 | A name pattern at any depth | Over-refuses an agent's own project (row C) |

**D2. Roots.** C, the running checkout, is `constitution_path()` minus `config/standing_orders/federation.md`, which equals `_PROJECT_ROOT.parent` (T0); W, the writer's root, is `root` (the working directory when None). They differ for `write_file` and `edit_file` always and for the others when the vessel is started from another directory; `--data-dir` moves neither; the build lane's worktree is a tree other than C (BF-897) and the lane does not call the rule; a non-editable install derives both from the environment (L2).

| # | Option | Judgement |
|---|---|---|
| A | W only | Fails in production: `../CLAUDE.md` and an absolute path reach the checkout outside `src` |
| B | C and W, each as written and as resolved (chosen) | The production shape, `..`, absolute paths, a vessel started elsewhere, a symlinked entry (the written form); a copy in another tree is not refused (the issue); tests move C as AD-1344's T10 does |
| C | Any tree, as `_names_constitution` | Refuses `pyproject.toml`, `.github/` or `CLAUDE.md` in an agent's own project |
| B+ | B plus the working directory for every writer | Closes the container case for `write_file` with a third, arbitrary root (L2) |

**D3. Shape.** `captain_document_write_refusal(path, root=None)` beside AD-1344's rule in `builder_paths.py` (already in `FIX_LOOP_PROTECTED_PATHS`), returning the reason or None as its siblings do; the reason names BF-943 and the governed routes (directives, AD-900, `DECISIONS.md:5685`; a build the Captain reviews). Not merged into AD-1344's or BF-911's rules (the issue's Do Not Build list; BF-911 rejected generalising AD-1344's rule, `DECISIONS.md:478`). **D4. The calls.** Each of the eight sites immediately after its AD-1344 block and before BF-911's call, with AD-1344's arguments, the site's error shape and a constant line `BF-943 <Class> refused operation=<op> reason_code=captain_document_refused` with no path (AD-1344 D20; BF-911 D15 to D17; T24). A path that is also the Constitution keeps AD-1344's reason.

**D5. Hard links.** For an existing regular file with `st_nlink != 1` the target is compared by `os.stat` identity with every existing file of every entry under each root (`os.walk`, links not followed), and an error refuses (chosen). Rejected: a scan on every write (a cost per write, and an unreadable subtree would refuse every write); comparing only the named files (misses the members of directory entries and the glob).

**D6. Census.** A sibling census in the new file (T30: the callers are the eight sites; T31: AD-1344's callers but the builder are this rule's). `_GUARDS` stays: it means any one rule, so adding this name lets a writer with one rule pass census B. **D7. Tests.** Real writers over `tmp_path` in production's shape, a control round and a neighbour after every refusal, every entry in eight spellings and three kinds of link, a guard on four real files; no network. Rejected: the rule alone (no seam); source-text scans (they cannot tell a required line from the shipped one). **D8. Severity.** High by the issue's rule (section 1). **D9. Documents and AD-1344's tests.** The `builder_paths.py` docstring (P2-1); `deterministic-ship.md` invariant 5's known-gaps cell gains one sentence (P3-3); `standing_orders.py` and `config/standing_orders/*` say nothing that changes (section 11). T24, T28, T33 and T38 of AD-1344's file wrote controls under the set through writers rooted in a tmp vessel (the issue names T28 only): each moves to a neighbour with a comment citing BF-943; none is renamed (`DECISIONS.md:466` cites T28, T33 and T38 by name, and T28's name still says "ship tier").

## 4. Milestones and gates

| M | Blocks | Gate |
|---|---|---|
| M1 | N1-1 to N1-5 | G1 |
| M2 | P2-1 to P2-14, then N2-1 (removing the marker) | G2 |
| M3 | P3-1 to P3-3, ledger | G3 |

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. **M0:** on the head, record the collected count (`--collect-only -q`) of every existing file named in G2.

- **G1.** `PY -m pytest tests/test_bf943_captain_document_write_refusal.py tests/test_ad1344_constitution_write_refusal.py -q -n 0 -p no:randomly`. **Expected:** the new file 21 passed (T0 to T5) and 464 xfailed (on Linux 463 and 1 skipped: T15); AD-1344's file all passed. The marker carries `raises=AssertionError, strict=True`: any other exception, or an XPASS, is a FAIL; any other count is a hard stop. Then the new file once with `--runxfail`: each failure must stop at the `assert` section 6 names, never at a premise line.
- **G2.** (1) `$f = git grep -l -E -e 'WriteFileTool|EditFileTool|FileWriterAgent|commit_write|DocxAgent|PptxAgent|XlsxAgent|submit_write_with_consensus|register_native_swe_tools|_mesh_write_file|constitution_write_refusal|protected_write_refusal|builder_write_refusal' -- 'tests/test_*.py'; PY -m pytest $f tests/test_ad1316_governed_effect_broker.py tests/test_ad1208_cost_bounded_turns.py tests/test_ad1224_durable_tool_start.py tests/test_ad1346_admission_file_write_census.py tests/test_ad1256_store_registry.py tests/test_ad1184_ad_ledger.py tests/test_ad1270b_architecture_fitness.py tests/test_ad1270b_seam_contracts.py tests/test_ad1324_srp_layout.py tests/test_layer_boundaries.py tests/test_standing_orders_layout.py -q -n 0 -p no:randomly`: the grep gave 35 files on the head (section 11); the 11 named files add the three that invoke `write_file` by id and the census, baseline and layout readers; the new file joins the grep once it exists. (2) `PY -P scripts/run_test_gate.py --preflight-only --label bf943` (its eight steps; section 11 says why none should move). **Expected:** the new file 485 passed (Linux 484 and 1 skipped); every other file 0 failed and collected counts equal M0; the preflight clean.
- **G3.** `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
- **Harness rule.** No source change made to pass a test, no skip, no loosened assertion. A failing case of the new file at G2 (any line), or any existing test failing, goes back to the Architect. The broad gate runs once, in the main session, with `--receipt`. The orchestrator records T4's result and G1's `--runxfail` reproduction (acceptance 1: `EditFileTool` changes `ship.md`, `WriteFileTool` creates `CLAUDE.md` and `.claude/agents/x.md`) on #1707.

## 5. Commit messages

- **M1:** `BF-943 M1: tests for the Captain's documents being refused by the agent-reachable writers, and four AD-1344 controls moved outside the set, xfail until built (#1707)`
- **M2:** `BF-943 M2: the agent-reachable writers refuse the Captain's governance, instruction and manifest files in the running checkout (#1707)`
- **M3:** `BF-943 M3: trackers, ledger and the ship invariant's gap (#1707)`; its body ends with the line `Closes #1707.`

## 6. Tests (`tests/test_bf943_captain_document_write_refusal.py`)

| Id | Cases | Covers | xfail until |
|---|---|---|---|
| T0 | 1 | Premise: `_PROJECT_ROOT` is `<checkout>/src`; the orders directory lies two levels below the checkout | none |
| T1 | 8 | Control round: each writer writes a neighbour | none |
| T2 | 7 | The rule allows neighbours, and CLAUDE.md, ship.md and a workflow in another tree; a link between two neighbours | none |
| T3 | 3 | A native build still modifies `ship.md`, an ontology file and `CLAUDE.md` in its worktree (acceptance 3) | none |
| T4 | 1 | A lieutenant's unoffered `write_file` through `DispatchToolExecutor` reaches the tool (the severity) | none |
| T5 | 1 | No script, hook or workflow names the rule or the set (acceptance 5) | none |
| T10 | 160 | The rule refuses each of 20 entries (13 existing, 7 absent) in 8 spellings | M2 |
| T11, T12 | 5 | An 8.3 form no alias backs (4); both roots: W, and C from `src` by `..` and from another root (1) | M2 |
| T13, T14 | 27 | A hard link to each existing entry, under a root and outside both (26); a junction (a symlink off Windows) into a document directory, and a document directory that is itself a link (1) | M2 |
| T15, T16, T17 | 3 | T15 (Windows only): a real 8.3 alias, an extended-length path, the extended UNC form; T16: failing closed at resolution, target and documents; T17: a `str` subclass | M2 |
| T20 | 240 | Each of 6 writers refuses each entry, relative and absolute, writes nothing, then writes a neighbour | M2 |
| T21 to T24 | 27 | `docx_revise` and `xlsx_update` under each of 7 directory entries (14); a hard link to `CLAUDE.md` through four writers (4); `write_file` under the strict-native context (1); a constant log line per writer (8) | M2 |
| T30, T31 | 2 | Census A and B (D6) | M2 |

**How each xfail case fails on the base** (by hand, section 11): T10 to T17 at `assert _refused(...)` (the looked-up stand-in answers None; T16's premise lines pass); T20 to T22 at `assert not written and _BF in error` (the writer writes, or answers `File not found` or `Parent directory does not exist`, so the tree check and the neighbour step are not reached); T23 at `assert result is not None ...` (the unfixed tree goes on into the strict-native lock and raises, which the case turns into None); T24 at `assert not written and "SENTINEL_PRIVATE_DIR" in error and _BF in error`; T30, T31 at the set comparison.

## 7. The contract

### 7.1 M1

**N1-1.** New file `tests/test_bf943_captain_document_write_refusal.py`:

```python
"""BF-943 (#1707): agents cannot rewrite the Captain's governance, instruction and manifest files in the running checkout.

The rule is ``builder_paths.captain_document_write_refusal``; the writers are ``write_file``, ``edit_file``, ``FileWriterAgent`` and the four
office writers, run on a temporary layout in production's shape: the running checkout is ``<tmp>/checkout`` (``_DEFAULT_ORDERS_DIR`` points
into it), ``swe_tools._PROJECT_ROOT`` is ``<checkout>/src``, the working directory is the checkout, the home directory is a temporary one.
The class holds the cases the unfixed tree fails; the functions before it pass on both. No BF-943 name is imported: the rule is looked up
once and, on the tree without it, refuses nothing.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.agents.file_writer import FileWriterAgent
from probos.cognitive import builder_paths, standing_orders
from probos.cognitive.agentic_dispatch import DispatchToolExecutor
from probos.cognitive.swe_harness import tools as swe_tools
from probos.cognitive.swe_harness.tools import EditFileTool, WriteFileTool, register_native_swe_tools
from probos.skill_framework import DocxAgent, PptxAgent, XlsxAgent
from probos.tools.registry import ToolRegistry
from probos.types import IntentMessage
from tests.test_ad1344_constitution_write_refusal import _CHANNEL_SUFFIXES, _build, _callee, _calls, _dir_link, _source, _tracked

_REPO = Path(__file__).resolve().parents[1]
_REAL = [_REPO / "CLAUDE.md", _REPO / "pyproject.toml", _REPO / "config" / "standing_orders" / "ship.md",
         _REPO / ".github" / "copilot-instructions.md"]
_BF, _BP = "BF-943", "src/probos/cognitive/builder_paths.py"
_RULE, _AD_RULE = "captain_document_write_refusal", "constitution_write_refusal"
_rule = getattr(builder_paths, _RULE, lambda path, root=None: None)  # without BF-943 nothing is refused
# One file per entry that exists today (a directory entry: one member), each holding "x v1"; and entries that exist nowhere today.
_FILES = ("config/standing_orders/ship.md", "config/standing_orders/crew_profiles/_default.yaml", "config/ontology/organization.yaml",
          "config/command_policy/starter.yaml", "config/sealed_modules.yaml", "CLAUDE.md", ".claude/agents/claude-builder.md",
          ".github/workflows/ci.yml", "pyproject.toml", "uv.lock", "ui/package.json", "ui/package-lock.json", "requirements-dev.txt")
_ABSENT = ("AGENTS.md", ".agents/skills/x.md", ".codex/config.toml", "requirements-extra.txt", "CODEOWNERS", ".github/CODEOWNERS",
           "docs/CODEOWNERS")
_NEIGHBOURS = ("docs/notes.md", "config/other.yaml", "config/standing_orders_notes.md", "pyproject.toml.bak", "requirements/dev.txt",
               "docs/CODEOWNERS.md", ".githubx/x.md")
_SPELLINGS = {"relative": lambda m: m, "dot-dot": lambda m: f"docs/../{m}", "case": str.upper, "trailing-dot": lambda m: m + ".",
              "trailing-space": lambda m: m + " ", "stream": lambda m: m + ":hidden"}
_SHORT = ("config/STANDI~9/ship.md", "PYPROJ~9.TOM", "GITHUB~9/workflows/ci.yml", "REQUIR~9.TXT")  # no such alias exists: lexical only
_WRITERS = ("write_file", "edit_file", "commit", "propose", "docx_create", "pptx_create")  # each reaches any entry
_OFFICE = ("docx_revise", "xlsx_update")  # each reaches a .docx or .xlsx under a directory entry
_LOG = {"write_file": ("WriteFileTool", "write_file"), "edit_file": ("EditFileTool", "edit_file"),
        "commit": ("FileWriterAgent", "commit_write"), "propose": ("FileWriterAgent", "propose_write"),
        "docx_create": ("DocxAgent", "docx_create"), "pptx_create": ("PptxAgent", "pptx_create"),
        "docx_revise": ("DocxAgent", "docx_revise"), "xlsx_update": ("XlsxAgent", "xlsx_update")}
_DIRECTORIES = ("config/standing_orders", "config/ontology", "config/command_policy", ".claude", ".agents", ".codex", ".github")
_EXPECTED_CALLERS = {("src/probos/cognitive/swe_harness/tools.py", "WriteFileTool.invoke"),
                     ("src/probos/cognitive/swe_harness/tools.py", "EditFileTool.invoke"),
                     ("src/probos/agents/file_writer.py", "FileWriterAgent.act"),
                     ("src/probos/agents/file_writer.py", "FileWriterAgent.commit_write"),
                     ("src/probos/skill_framework.py", "DocxAgent.create_docx"), ("src/probos/skill_framework.py", "DocxAgent.revise_docx"),
                     ("src/probos/skill_framework.py", "PptxAgent.create_pptx"), ("src/probos/skill_framework.py", "XlsxAgent.update_xlsx")}


@pytest.fixture(autouse=True)
def _real_documents_untouched():
    before = [(p.read_bytes(), os.stat(p).st_mode) for p in _REAL]
    yield
    assert [(p.read_bytes(), os.stat(p).st_mode) for p in _REAL] == before, "a real Captain document changed"


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "checkout"
    for rel in (*_FILES, "docs/notes.md", "config/other.yaml"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x v1\n", encoding="utf-8")
    (root / "src").mkdir()
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setattr(standing_orders, "_DEFAULT_ORDERS_DIR", root / "config" / "standing_orders")
    monkeypatch.setattr(swe_tools, "_PROJECT_ROOT", root / "src")
    monkeypatch.chdir(root)
    assert Path.cwd() == root.resolve() and standing_orders.standing_orders_dir().parent.parent == root, "premise: the layout"
    return root


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _link(source: Path, alias: Path) -> Path:
    alias.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, alias)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"hard links are unavailable here: {exc}")
    assert os.path.samefile(alias, source), "premise: the alias is the same file"
    return alias


def _refused(reason: str | None) -> bool:
    return reason is not None and _BF in reason


def _office_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".docx":
        from docx import Document

        Document().save(str(path))
    else:
        from openpyxl import Workbook

        Workbook().save(str(path))
    return path


async def _call(writer: str, path: str) -> tuple[bool, str]:
    """(written, error) of one writer for a path; each keeps its own error shape (a result, a dict, a raise)."""
    if writer == "write_file":
        result = await WriteFileTool(SimpleNamespace()).invoke({"path": path, "content": "AMENDED\n"})
        return result.success, result.error or ""
    if writer == "edit_file":
        result = await EditFileTool(SimpleNamespace()).invoke({"path": path, "old_text": "v1", "new_text": "AMENDED"})
        return result.success, result.error or ""
    if writer == "commit":
        done = await FileWriterAgent.commit_write(path, "AMENDED\n")
        return done["success"], done.get("error", "")
    agent, intent, params = {
        "propose": (FileWriterAgent(pool="filesystem"), "write_file", {"path": path, "content": "AMENDED\n"}),
        "docx_create": (DocxAgent(pool="office"), "docx_create", {"title": "t", "content": ["x"], "output_path": path}),
        "pptx_create": (PptxAgent(pool="office"), "pptx_create",
                        {"title": "t", "slides": [{"title": "x", "bullets": ["y"]}], "output_path": path}),
        "docx_revise": (DocxAgent(pool="office"), "docx_revise", {"file_path": path, "instructions": "amend"}),
        "xlsx_update": (XlsxAgent(pool="office"), "xlsx_update", {"file_path": path, "sheet": "Sheet", "updates": {"A1": "amended"}}),
    }[writer]
    if writer == "propose":
        await agent.start()
    try:
        result = await agent.handle_intent(IntentMessage(intent=intent, params=params))
    except PermissionError as exc:
        return False, str(exc)
    return (result.success, result.error or "") if result else (False, "no result")


def _callers(*names: str) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for rel in _tracked("src/probos"):
        if rel.endswith(".py"):
            found |= {(rel, scope) for scope, call in _calls(_source(rel)) if _callee(call) in names}
    return found


# ── Guards and controls: these pass on both trees ─────────────────────────


def test_the_swe_root_is_the_src_directory_and_the_checkout_is_derived_from_the_orders() -> None:
    """T0, D2's premise: in production ``_PROJECT_ROOT`` is ``<checkout>/src``, and the orders directory lies two levels below the checkout."""
    root = Path(swe_tools.__file__).resolve().parents[3]
    assert swe_tools._PROJECT_ROOT == root and root.name == "src"
    assert standing_orders.standing_orders_dir() == root.parent / "config" / "standing_orders"


@pytest.mark.parametrize("writer", [*_WRITERS, *_OFFICE])
async def test_every_writer_writes_a_neighbour(checkout: Path, writer: str) -> None:
    """T1, the control round: the neighbour a refusal test pairs with is written by the same writer."""
    target = checkout / "docs" / ("n.docx" if writer == "docx_revise" else "n.xlsx" if writer == "xlsx_update" else "notes.md")
    if writer in _OFFICE:
        _office_file(target)
    before = target.read_bytes() if target.exists() else None
    written, error = await _call(writer, str(target))
    assert written, error
    assert writer == "propose" or before is None or target.read_bytes() != before  # a proposal writes nothing until the vote


@pytest.mark.parametrize("neighbour", _NEIGHBOURS)
def test_the_rule_allows_a_neighbour_and_a_document_in_another_tree(checkout: Path, tmp_path: Path, neighbour: str) -> None:
    """T2: a name that only looks like an entry, and documents in a tree that is neither root."""
    assert _rule(neighbour, checkout) is None and _rule(str(checkout / neighbour), checkout) is None
    for member in ("CLAUDE.md", "config/standing_orders/ship.md", ".github/workflows/ci.yml"):
        assert _rule(str(tmp_path / "other" / member), checkout) is None, member
    alias = _link(checkout / "docs" / "notes.md", checkout / "docs" / "again.md")
    assert _rule(str(alias), checkout) is None, "a file with another name that is no document's"


@pytest.mark.parametrize("member", ["config/standing_orders/ship.md", "config/ontology/organization.yaml", "CLAUDE.md"])
async def test_a_native_build_still_modifies_a_document_in_its_worktree(checkout: Path, member: str) -> None:
    """T3, acceptance 3: the build lane writes through ``builder_write_refusal``, not through this rule."""
    result, commit = await _build(checkout, [{"path": member, "mode": "modify", "replacements": [{"search": "v1", "replace": "v2"}]}])
    assert not result.error, result.error
    assert (checkout / member).read_text(encoding="utf-8") == "x v2\n" and member in commit.await_args.args[0]


async def test_a_lieutenants_unoffered_write_file_call_reaches_the_tool_on_the_dm_route(
    checkout: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T4, acceptance 1 and the severity: the DM route's executor runs a registered tool the model was never offered.

    The route builds ``DispatchToolExecutor(registry=)`` with no confinement and offers only the Captain's grants; the loop's call passes no
    ``required``, so ``check_and_invoke`` asks for READ, and the rank matrix gives a lieutenant WRITE. A pass on both trees (it is about the
    route, not the rule); if it fails the route is closed and P3-1 says Medium.
    """
    registry = ToolRegistry()
    register_native_swe_tools(registry, SimpleNamespace())
    reached: list[str] = []
    real = WriteFileTool.invoke

    async def spy(self, params, context=None):  # type: ignore[no-untyped-def]
        reached.append(params["path"])
        return await real(self, params, context)

    monkeypatch.setattr(WriteFileTool, "invoke", spy)
    target = str(checkout / "docs" / "dm.md")
    result = await DispatchToolExecutor(registry=registry).invoke(
        agent_id="lt-1", tool_id="write_file", params={"path": target, "content": "x"},
        agent_department="engineering", agent_rank="lieutenant", context={})
    assert reached == [target] and result.success, result.error


def test_census_the_captains_channels_do_not_consult_the_rule() -> None:
    """T5, acceptance 5 (AD-1344's T36): no tracked script, hook or workflow names the rule or the set."""
    channels = [rel for rel in _tracked("scripts", ".github", ".githooks", ".pre-commit-config.yaml") if rel.endswith(_CHANNEL_SUFFIXES)]
    assert any(rel.startswith(".github/workflows/") for rel in channels), "premise: CI is tracked and scanned"
    for rel in channels:
        text = (_REPO / rel).read_text(encoding="utf-8", errors="replace")
        assert _RULE not in text and "CAPTAIN_DOCUMENT_PATHS" not in text, rel


# ── The cases the unfixed tree fails ──────────────────────────────────────


class TestWhatTheBaseDoesNotRefuse:
    # BF-943 M1: xfail until M2 builds it (M2 removes this line and the next).
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-943 M2 builds it")

    @pytest.mark.parametrize("spelling", [*_SPELLINGS, "absolute", "absolute without a root"])
    @pytest.mark.parametrize("member", (*_FILES, *_ABSENT))
    def test_the_rule_refuses_every_entry_in_every_spelling(self, checkout: Path, member: str, spelling: str) -> None:
        """T10: relative, absolute (with and without a root), with ``..``, a case variant, a trailing dot or space, a stream."""
        if spelling.startswith("absolute"):
            refusal = _rule(str(checkout / member), None if spelling.endswith("root") else checkout)
        else:
            refusal = _rule(_SPELLINGS[spelling](member), checkout)
        assert _refused(refusal), refusal

    @pytest.mark.parametrize("form", _SHORT)
    def test_the_rule_refuses_an_8_3_short_form(self, checkout: Path, form: str) -> None:
        """T11: the lexical form, a ``~digit`` component with the first two characters of an entry's."""
        assert _refused(_rule(form, checkout)), form

    def test_the_rule_judges_the_checkout_and_the_writers_root(self, checkout: Path, tmp_path: Path) -> None:
        """T12, D2: the writer's root; the checkout reached from ``src`` by ``..`` or from another root by an absolute path."""
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        assert _refused(_rule("config/standing_orders/x.md", elsewhere)), "below the writer's root"
        assert _refused(_rule("../CLAUDE.md", checkout / "src")), "the checkout, from the SWE root"
        assert _refused(_rule(str(checkout / ".github" / "x.yml"), elsewhere)), "the checkout, from another root"
        assert _rule("../docs/n.md", checkout / "src") is None and _rule(str(elsewhere / "docs" / "n.md"), checkout) is None

    @pytest.mark.parametrize("where", ["docs/alias.md", "../outside/alias.md"])
    @pytest.mark.parametrize("member", _FILES)
    def test_a_hard_link_to_a_document_is_refused(self, checkout: Path, where: str, member: str) -> None:
        """T13: an existing file with another name that is a document's, under either root or outside both."""
        assert _refused(_rule(str(_link(checkout / member, (checkout / where).resolve())), checkout)), where

    def test_a_directory_link_is_refused_both_ways(self, checkout: Path) -> None:
        """T14: through a junction (a symlink off Windows) into a document directory; and for a document directory that is itself a link."""
        _dir_link(checkout / "docs" / "orders", checkout / "config" / "standing_orders")
        assert _refused(_rule("docs/orders/new.md", checkout)), "through a link"
        (checkout.parent / "codex-target").mkdir()
        _dir_link(checkout / ".codex", checkout.parent / "codex-target")
        assert _refused(_rule(".codex/config.toml", checkout)), "the written form of a document directory that is a link"

    @pytest.mark.skipif(os.name != "nt", reason="8.3 aliases and extended-length paths are Windows forms")
    def test_a_real_8_3_alias_and_an_extended_length_path_are_refused(self, checkout: Path) -> None:
        """T15: Windows only (this host, not the Linux CI): resolution expands a real alias; the extended-length prefix is dropped."""
        import ctypes

        buffer = ctypes.create_unicode_buffer(1024)
        if not ctypes.windll.kernel32.GetShortPathNameW(str(checkout / "config" / "standing_orders"), buffer, 1024):
            pytest.skip("8.3 names are not available on this volume")
        assert _refused(_rule(str(Path(buffer.value) / "new.md"), checkout)), buffer.value
        assert _refused(_rule("\\\\?\\" + str(checkout / "CLAUDE.md"), checkout))
        parts = builder_paths._document_parts  # a pure function: the extended UNC form names the same share
        assert parts(Path("\\\\?\\UNC\\host\\share\\a\\CLAUDE.md")) == parts(Path("\\\\host\\share\\a\\CLAUDE.md"))

    def test_a_path_that_cannot_be_resolved_or_examined_is_refused(self, checkout: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """T16: failing closed at the resolution, the target and the documents (premise lines first)."""
        _link(checkout / "docs" / "notes.md", checkout / "docs" / "again.md")
        for name in ("probe.md", "notes.md", "again.md"):
            assert _rule(f"docs/{name}", checkout) is None, "premise: accepted before the patches"
        real_resolve, real_stat = Path.resolve, os.stat

        def resolve(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            if self.name == "probe.md":
                raise ValueError("unresolvable")
            return real_resolve(self, *args, **kwargs)

        def stat(path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if Path(path).name in ("notes.md", "CLAUDE.md"):
                raise PermissionError(13, "denied")
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", resolve)
        resolved = _rule("docs/probe.md", checkout)
        monkeypatch.undo()
        monkeypatch.setattr(builder_paths.os, "stat", stat)
        target, documents = _rule("docs/notes.md", checkout), _rule("docs/again.md", checkout)
        monkeypatch.undo()
        assert _refused(resolved) and "(resolved: ValueError)" in resolved
        assert _refused(target) and "(target: PermissionError)" in target
        assert _refused(documents) and "(documents: PermissionError)" in documents

    def test_a_value_that_is_not_an_exact_str_is_refused(self, checkout: Path) -> None:
        """T17: the type is compared first (AD-1344's D14)."""

        class Text(str):
            pass

        refusal = _rule(Text("docs/notes.md"), checkout)
        assert _refused(refusal) and "exact str" in refusal
        assert _rule("docs/notes.md", checkout) is None  # control: the same text, an exact str

    @pytest.mark.parametrize("form", ["relative", "absolute"])
    @pytest.mark.parametrize("member", (*_FILES, *_ABSENT))
    @pytest.mark.parametrize("writer", _WRITERS)
    async def test_each_writer_refuses_every_entry_and_still_writes_a_neighbour(
        self, checkout: Path, writer: str, member: str, form: str,
    ) -> None:
        """T20, acceptance 2: each general writer, each entry, rooted as that writer roots a relative path; nothing is written."""
        before = _tree(checkout)
        written, error = await _call(writer, member if form == "relative" else str(checkout / member))
        assert not written and _BF in error, error
        assert _tree(checkout) == before
        written, error = await _call(writer, str(checkout / "docs" / "notes.md"))
        assert written, error

    @pytest.mark.parametrize("writer", _OFFICE)
    @pytest.mark.parametrize("directory", _DIRECTORIES)
    async def test_the_office_revise_and_update_refuse_a_file_under_a_document_directory(
        self, checkout: Path, writer: str, directory: str,
    ) -> None:
        """T21: an existing .docx or .xlsx under a directory entry, then the neighbour."""
        suffix = ".docx" if writer == "docx_revise" else ".xlsx"
        target = _office_file(checkout / directory / ("x" + suffix))
        before = target.read_bytes()
        written, error = await _call(writer, str(target))
        assert not written and _BF in error, error
        assert target.read_bytes() == before
        written, error = await _call(writer, str(_office_file(checkout / "docs" / ("n" + suffix))))
        assert written, error

    @pytest.mark.parametrize("writer", ["write_file", "edit_file", "commit", "docx_create"])
    async def test_a_hard_link_to_a_document_is_refused_by_the_writers(self, checkout: Path, writer: str) -> None:
        """T22, acceptance 2: through the alias the writer is given, the document is unchanged."""
        written, error = await _call(writer, str(_link(checkout / "CLAUDE.md", checkout / "docs" / "alias.md")))
        assert not written and _BF in error, error
        assert (checkout / "CLAUDE.md").read_text(encoding="utf-8") == "x v1\n"

    async def test_write_file_refuses_under_the_effect_broker_context(self, checkout: Path) -> None:
        """T23: the refusal comes before the strict-native lock (the unfixed tree goes on into it and raises)."""
        context = {"_effect_dispatch_context": object(), "_strict_native_target": str(checkout / "CLAUDE.md"),
                   "_strict_native_root": str(checkout)}
        try:
            result = await WriteFileTool(SimpleNamespace()).invoke({"path": str(checkout / "CLAUDE.md"), "content": "AMENDED\n"}, context)
        except Exception:
            result = None
        assert result is not None and not result.success and _BF in (result.error or "")
        assert (checkout / "CLAUDE.md").read_text(encoding="utf-8") == "x v1\n"

    @pytest.mark.parametrize("writer", list(_LOG))
    async def test_a_refusal_logs_a_constant_line_without_the_callers_path(
        self, checkout: Path, writer: str, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """T24, D4 (AD-1344's D20, BF-911's D15 to D17): the operation and the reason code, not the path."""
        caplog.set_level("WARNING")
        if writer in _OFFICE:
            document = _office_file(checkout / ".github" / "SENTINEL_PRIVATE_DIR" / ("x.docx" if writer == "docx_revise" else "x.xlsx"))
        else:
            document = checkout / "SENTINEL_PRIVATE_DIR" / ".." / "CLAUDE.md"
        written, error = await _call(writer, str(document))
        assert not written and "SENTINEL_PRIVATE_DIR" in error and _BF in error, error
        owner, operation = _LOG[writer]
        assert f"BF-943 {owner} refused operation={operation} reason_code=captain_document_refused" in caplog.text
        assert "SENTINEL_PRIVATE_DIR" not in caplog.text

    def test_census_the_rule_is_called_by_the_inventoried_writers(self) -> None:
        """T30, census A: the callers are the eight writers; the build lane's modules are not among them."""
        assert _callers(_RULE) == _EXPECTED_CALLERS

    def test_census_every_caller_of_ad1344s_rule_but_the_builder_calls_this_one(self) -> None:
        """T31, census B and acceptance 4: a writer that calls AD-1344's rule and not this one fails."""
        constitution = _callers(_AD_RULE)
        assert (_BP, "builder_write_refusal") in constitution, "premise"
        assert constitution - {(_BP, "builder_write_refusal")} == _callers(_RULE)
```

**N1-2.** `tests/test_ad1344_constitution_write_refusal.py` (T24: the controls move)
SEARCH:
```
    for rel, text in (("config/standing_orders/ship.md", "SHIP v2\n"), ("config/other.yaml", "other: 2\n"),
                      ("config/standing_orders/federation_notes.md", "notes\n")):
```
REPLACE:
```
    # BF-943: the ship tier and federation_notes.md are in CAPTAIN_DOCUMENT_PATHS, so the controls are neighbours outside it.
    for rel, text in (("docs/notes.md", "SHIP v2\n"), ("config/other.yaml", "other: 2\n"),
                      ("docs/federation_notes.md", "notes\n")):
```

**N1-3.** `tests/test_ad1344_constitution_write_refusal.py` (T28, the pinned test)
SEARCH:
```
    """T28."""
    tool = EditFileTool(SimpleNamespace())
    ship = await tool.invoke({"path": "config/standing_orders/ship.md", "old_text": "SHIP v1", "new_text": "SHIP v2"})
```
REPLACE:
```
    """T28 (BF-943: the control edit is a neighbour outside CAPTAIN_DOCUMENT_PATHS; the name is kept for the AD-1344 record)."""
    tool = EditFileTool(SimpleNamespace())
    (swe_root / "docs" / "notes.md").write_text(_SHIP, encoding="utf-8")  # BF-943: ship.md is in the set, notes.md is not
    ship = await tool.invoke({"path": "docs/notes.md", "old_text": "SHIP v1", "new_text": "SHIP v2"})
```

**N1-4.** `tests/test_ad1344_constitution_write_refusal.py` (T38)
SEARCH:
```
    ship = "config/standing_orders/ship.md"
    written = _ShiftingPath(ship, CONSTITUTION_RELATIVE_PATH)
```
REPLACE:
```
    ship = "docs/notes.md"  # BF-943: not config/standing_orders/ship.md, which is in CAPTAIN_DOCUMENT_PATHS
    written = _ShiftingPath(ship, CONSTITUTION_RELATIVE_PATH)
```

**N1-5.** `tests/test_ad1344_constitution_write_refusal.py` (T33)
SEARCH:
```
    notes = vessel / "config" / "standing_orders" / "notes.docx"
    await DocxAgent(pool="office").create_docx(title="Notes", content=["x"], output_path=str(notes))
```
REPLACE:
```
    notes = vessel / "docs" / "notes.docx"  # BF-943: not under config/standing_orders, which is in CAPTAIN_DOCUMENT_PATHS
    await DocxAgent(pool="office").create_docx(title="Notes", content=["x"], output_path=str(notes))
```

### 7.2 M2

**P2-1.** `src/probos/cognitive/builder_paths.py` (module docstring)
SEARCH:
```
cases. ``builder_write_refusal`` calls it, and so do the writers listed in
``tests/test_ad1344_constitution_write_refusal.py`` (``_EXPECTED_CALLERS``).
"""
```
REPLACE:
```
cases. ``builder_write_refusal`` calls it, and so do the writers listed in
``tests/test_ad1344_constitution_write_refusal.py`` (``_EXPECTED_CALLERS``).

BF-943 (#1707): ``captain_document_write_refusal`` refuses a write to an entry of ``CAPTAIN_DOCUMENT_PATHS`` (the
Captain's standing orders and other governance files, instruction files, workflows and manifests) below the running
checkout or the writer's root. The writers listed in ``tests/test_bf943_captain_document_write_refusal.py``
(``_EXPECTED_CALLERS``) call it after AD-1344's rule. ``builder_write_refusal`` does not: a build runs in a linked
worktree and reaches the checkout through the Captain's merge review.
"""
```

**P2-2.** `src/probos/cognitive/builder_paths.py` (imports)
SEARCH:
```
import os
import posixpath
import re
import unicodedata
from pathlib import Path
```
REPLACE:
```
import os
import posixpath
import re
import stat
import unicodedata
from collections.abc import Iterator, Sequence
from fnmatch import fnmatchcase
from pathlib import Path
```

**P2-3.** `src/probos/cognitive/builder_paths.py` (the rule, after `constitution_write_refusal`)
SEARCH:
```
        if os.path.samestat(current, constitution):
            return _constitution_refusal(path)
    return None


def builder_write_refusal(
```
REPLACE:
```
        if os.path.samestat(current, constitution):
            return _constitution_refusal(path)
    return None


# BF-943 (#1707): the Captain's documents in a checkout: the orders, ontology, command policy and sealed list ProbOS loads,
# the instruction files, workflows and CODEOWNERS the Captain's coding agents and CI load, and the manifests an install
# reads. A trailing "/" names a directory and all below it; "*" matches within one component. An entry is judged below the
# running checkout and below the writer's root: a copy in another tree is not named, and a name absent today is.
CAPTAIN_DOCUMENT_PATHS = (
    "config/standing_orders/",
    "config/ontology/",
    "config/command_policy/",
    "config/sealed_modules.yaml",
    "CLAUDE.md",
    "AGENTS.md",
    ".claude/",
    ".agents/",
    ".codex/",
    ".github/",
    "pyproject.toml",
    "uv.lock",
    "requirements*.txt",
    "ui/package.json",
    "ui/package-lock.json",
    "CODEOWNERS",
    "docs/CODEOWNERS",
)
_CAPTAIN_DOCUMENT_PARTS = tuple(
    tuple(_canonical(part) for part in entry.rstrip("/").split("/")) for entry in CAPTAIN_DOCUMENT_PATHS
)
_DOCUMENT_NOT_A_STR = "Captain document write refused (BF-943): the path is not an exact str, so it is not checked"


def _captain_document_refusal(path_text: str) -> str:
    return (
        f"Captain document write refused (BF-943): {path_text!r} is one of the Captain's governance, instruction or "
        "manifest files in a checkout (builder_paths.CAPTAIN_DOCUMENT_PATHS), which an agent does not write; standing "
        "orders change through directives, and the other files through a build the Captain reviews"
    )


def _captain_document_unverifiable(path_text: str, stage: str, exc: BaseException) -> str:
    return (
        f"Captain document write refused (BF-943): cannot verify that {path_text!r} is not one of the Captain's "
        f"documents ({stage}: {_exception_name(exc)})"
    )


def _running_checkout() -> Path:
    """The project root the running vessel reads its standing orders from: the directory above ``config/standing_orders``."""
    return Path(*constitution_path().parts[: -len(_CONSTITUTION_RELATIVE_PARTS)])


def _document_component(name: str, expected: str) -> bool:
    """Whether canonical *name* is an entry's component (``*`` globs) or an 8.3 short form with its first two characters."""
    if fnmatchcase(name, expected):
        return True
    return _SHORT_NAME.search(name) is not None and name[:2] == expected.lstrip(".")[:2]  # a short name has no leading dot


def _document_parts(absolute: Path) -> tuple[str, ...]:
    """The anchor and components of an absolute path as the rule compares them: no Windows extended-length prefix, no ``:`` suffix, canonical."""
    text = str(absolute)
    if text[:8].upper() == "\\\\?\\UNC\\":
        text = "\\\\" + text[8:]
    elif text[:4] in ("\\\\?\\", "\\\\.\\"):
        text = text[4:]
    parts = Path(text).parts
    names = (_canonical(part.split(":", 1)[0]) for part in parts[1:])
    return (_canonical(parts[0]), *(name for name in names if name))


def _names_a_document(target: Path, roots: Sequence[Path]) -> bool:
    """Whether absolute *target* lies below one of the absolute *roots* at an entry of ``CAPTAIN_DOCUMENT_PATHS``."""
    parts = _document_parts(target)
    for root in roots:
        top = _document_parts(root)
        below = parts[len(top):]
        if parts[: len(top)] == top and any(
            len(below) >= len(entry) and all(_document_component(name, expected) for name, expected in zip(below, entry))
            for entry in _CAPTAIN_DOCUMENT_PARTS
        ):
            return True
    return False


def _raise(exc: OSError) -> None:
    raise exc


def _document_files(root: Path) -> Iterator[Path]:
    """Every existing file of an entry of ``CAPTAIN_DOCUMENT_PATHS`` below *root*; a link to a directory is not followed."""
    for entry in CAPTAIN_DOCUMENT_PATHS:
        for found in root.glob(entry.rstrip("/")):
            if found.is_dir():
                for directory, _names, files in os.walk(found, onerror=_raise):
                    for name in files:
                        yield Path(directory) / name
            else:
                yield found


def _is_a_second_name_of_a_document(current: os.stat_result, roots: Sequence[Path]) -> bool:
    """Whether *current* (an ``os.stat``) is that of an existing file of an entry below one of *roots*."""
    for root in roots:
        for document in _document_files(root):
            try:
                if os.path.samestat(current, os.stat(document)):
                    return True
            except (FileNotFoundError, NotADirectoryError):
                continue  # gone since it was listed: nothing to alias
    return False


def captain_document_write_refusal(
    path: str, root: str | os.PathLike[str] | None = None,
) -> str | None:
    """BF-943 (#1707): why an agent-reachable writer must not write *path*, or None if it may.

    *path* is as the writer received it: relative to *root* (the working directory when None) or absolute. Refused, naming BF-943: a value
    that is not an exact ``str``; a path that, as written or once resolved, lies below the running checkout (the directory above
    ``constitution_path()``'s ``config/standing_orders``) or *root* at an entry of ``CAPTAIN_DOCUMENT_PATHS``, existing or not; an existing
    regular file with more than one link that has the ``os.stat`` identity of an existing file of an entry; an ``OSError``, ``RuntimeError``
    or ``ValueError`` while resolving, examining or listing. A document in another tree is not refused. Any other exception propagates.
    """
    if type(path) is not str:
        return _DOCUMENT_NOT_A_STR
    try:
        writer_root = Path.cwd() if root is None else Path(root)
        roots = [_running_checkout(), writer_root]
        target = Path(path)
        if not target.is_absolute():
            target = writer_root / target
        if _names_a_document(Path(os.path.abspath(target)), [Path(os.path.abspath(r)) for r in roots]):
            return _captain_document_refusal(path)
        resolved_roots = list(dict.fromkeys(r.resolve(strict=False) for r in roots))
        if _names_a_document(target.resolve(strict=False), resolved_roots):
            return _captain_document_refusal(path)
    except (OSError, RuntimeError, ValueError) as exc:
        return _captain_document_unverifiable(path, "resolved", exc)
    try:
        current = os.stat(target)
    except (FileNotFoundError, NotADirectoryError):
        return None  # not on disk, so not a second name of an existing file
    except (OSError, ValueError) as exc:
        return _captain_document_unverifiable(path, "target", exc)
    if not stat.S_ISREG(current.st_mode) or current.st_nlink == 1:
        return None  # only a regular file with another name can be a second name of a document
    try:
        if _is_a_second_name_of_a_document(current, resolved_roots):
            return _captain_document_refusal(path)
    except (OSError, ValueError) as exc:
        return _captain_document_unverifiable(path, "documents", exc)
    return None


def builder_write_refusal(
```

**P2-4.** `src/probos/cognitive/swe_harness/tools.py` (import)
SEARCH:
```
from probos.cognitive.builder_paths import constitution_write_refusal
```
REPLACE:
```
from probos.cognitive.builder_paths import captain_document_write_refusal, constitution_write_refusal
```

**P2-5.** `src/probos/cognitive/swe_harness/tools.py` (`WriteFileTool.invoke`)
SEARCH:
```
            refused = protected_write_refusal(path_text, root=_PROJECT_ROOT, runtime=self._runtime)  # BF-911: write_file
```
REPLACE:
```
            refused = captain_document_write_refusal(path_text, _PROJECT_ROOT)  # BF-943: write_file
            if refused is not None:
                logger.warning("BF-943 WriteFileTool refused operation=write_file reason_code=captain_document_refused")
                return ToolResult(error=refused)
            refused = protected_write_refusal(path_text, root=_PROJECT_ROOT, runtime=self._runtime)  # BF-911: write_file
```

**P2-6.** `src/probos/cognitive/swe_harness/tools.py` (`EditFileTool.invoke`)
SEARCH:
```
            refused = protected_write_refusal(path_text, root=_PROJECT_ROOT, runtime=self._runtime)  # BF-911: edit_file
```
REPLACE:
```
            refused = captain_document_write_refusal(path_text, _PROJECT_ROOT)  # BF-943: edit_file
            if refused is not None:
                logger.warning("BF-943 EditFileTool refused operation=edit_file reason_code=captain_document_refused")
                return ToolResult(error=refused)
            refused = protected_write_refusal(path_text, root=_PROJECT_ROOT, runtime=self._runtime)  # BF-911: edit_file
```

**P2-7.** `src/probos/agents/file_writer.py` (import)
SEARCH:
```
from probos.cognitive.builder_paths import constitution_write_refusal
```
REPLACE:
```
from probos.cognitive.builder_paths import captain_document_write_refusal, constitution_write_refusal
```

**P2-8.** `src/probos/agents/file_writer.py` (`FileWriterAgent.act`)
SEARCH:
```
                refused = protected_write_refusal(str(p), runtime=self._runtime)  # BF-911: the proposal
```
REPLACE:
```
                refused = captain_document_write_refusal(str(p), Path.cwd())  # BF-943: the proposal
                if refused is not None:
                    logger.warning("BF-943 FileWriterAgent refused operation=propose_write reason_code=captain_document_refused")
                    return {"success": False, "error": refused}
                refused = protected_write_refusal(str(p), runtime=self._runtime)  # BF-911: the proposal
```

**P2-9.** `src/probos/agents/file_writer.py` (`FileWriterAgent.commit_write`)
SEARCH:
```
            refused = protected_write_refusal(str(p), runtime=runtime)  # BF-911: the write
```
REPLACE:
```
            refused = captain_document_write_refusal(str(p), Path.cwd())  # BF-943: the write
            if refused is not None:
                logger.warning("BF-943 FileWriterAgent refused operation=commit_write reason_code=captain_document_refused")
                return {"success": False, "error": refused}
            refused = protected_write_refusal(str(p), runtime=runtime)  # BF-911: the write
```

**P2-10.** `src/probos/skill_framework.py` (import)
SEARCH:
```
from probos.cognitive.builder_paths import constitution_write_refusal
```
REPLACE:
```
from probos.cognitive.builder_paths import captain_document_write_refusal, constitution_write_refusal
```

**P2-11.** `src/probos/skill_framework.py` (`DocxAgent.create_docx`)
SEARCH:
```
            refused = protected_write_refusal(str(target), runtime=self._runtime)  # BF-911: docx_create
```
REPLACE:
```
            refused = captain_document_write_refusal(str(target), Path.cwd())  # BF-943: docx_create
            if refused is not None:
                logger.warning("BF-943 DocxAgent refused operation=docx_create reason_code=captain_document_refused")
                raise PermissionError(refused)
            refused = protected_write_refusal(str(target), runtime=self._runtime)  # BF-911: docx_create
```

**P2-12.** `src/probos/skill_framework.py` (`DocxAgent.revise_docx`)
SEARCH:
```
        refused = protected_write_refusal(str(source), runtime=self._runtime)  # BF-911: docx_revise
```
REPLACE:
```
        refused = captain_document_write_refusal(str(source), Path.cwd())  # BF-943: docx_revise
        if refused is not None:
            logger.warning("BF-943 DocxAgent refused operation=docx_revise reason_code=captain_document_refused")
            raise PermissionError(refused)
        refused = protected_write_refusal(str(source), runtime=self._runtime)  # BF-911: docx_revise
```

**P2-13.** `src/probos/skill_framework.py` (`PptxAgent.create_pptx`)
SEARCH:
```
            refused = protected_write_refusal(str(target), runtime=self._runtime)  # BF-911: pptx_create
```
REPLACE:
```
            refused = captain_document_write_refusal(str(target), Path.cwd())  # BF-943: pptx_create
            if refused is not None:
                logger.warning("BF-943 PptxAgent refused operation=pptx_create reason_code=captain_document_refused")
                raise PermissionError(refused)
            refused = protected_write_refusal(str(target), runtime=self._runtime)  # BF-911: pptx_create
```

**P2-14.** `src/probos/skill_framework.py` (`XlsxAgent.update_xlsx`)
SEARCH:
```
        refused = protected_write_refusal(str(source), runtime=self._runtime)  # BF-911: xlsx_update
```
REPLACE:
```
        refused = captain_document_write_refusal(str(source), Path.cwd())  # BF-943: xlsx_update
        if refused is not None:
            logger.warning("BF-943 XlsxAgent refused operation=xlsx_update reason_code=captain_document_refused")
            raise PermissionError(refused)
        refused = protected_write_refusal(str(source), runtime=self._runtime)  # BF-911: xlsx_update
```

**N2-1.** `tests/test_bf943_captain_document_write_refusal.py` (the marker comes off)
SEARCH:
```
    # BF-943 M1: xfail until M2 builds it (M2 removes this line and the next).
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-943 M2 builds it")

    @pytest.mark.parametrize("spelling", [*_SPELLINGS, "absolute", "absolute without a root"])
```
REPLACE:
```
    @pytest.mark.parametrize("spelling", [*_SPELLINGS, "absolute", "absolute without a root"])
```

### 7.3 M3: tracking

**P3-1.** `PROGRESS.md`. BF-942's entry is the newest; the new one goes above it. Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

**BF-942 (
```
REPLACE:
```
# ProbOS Progress

**BF-943 (DATE), #1707 -- the agent-reachable file writers refuse the Captain's governance, instruction and manifest files in the running checkout.**
- **Base.** `write_file`, `edit_file`, `FileWriterAgent` and the office writers refused only the Constitution (AD-1344) and the loaded config and vault files (BF-911); the other standing-orders tiers, `config/ontology/`, `config/sealed_modules.yaml`, `CLAUDE.md`, `.claude/`, `.github/`, CODEOWNERS and the lock files and manifests could be rewritten by any lieutenant or above. On the DM route a lieutenant's unoffered `write_file` reaches the tool (severity High by the issue's rule; T4).
- **Fix.** `builder_paths.captain_document_write_refusal(path, root)` over `CAPTAIN_DOCUMENT_PATHS` (17 entries) refuses a path below the running checkout or the writer's root at an entry, as written or resolved, or a hard link to one; the eight call sites of AD-1344's rule outside the builder call it after that rule. A copy in another tree, the build lane and the Captain's channels are untouched. Contract `prompts/bf-943-captain-document-write-refusal.md`. Closes #1707.

**BF-942 (
```

**P3-2.** `DECISIONS.md`. Append after BF-942's entry. Its last bullet occurs once. Replace `DATE` with M3's date.
SEARCH:
```
- *Residual.* L1 to L10 of the contract. *Reversal.* Revert the BF-942 commits (the table stays and is ignored).
```
REPLACE:
```
- *Residual.* L1 to L10 of the contract. *Reversal.* Revert the BF-942 commits (the table stays and is ignored).

### BF-943 -- Agents cannot rewrite the Captain's governance, instruction and manifest files in the running checkout (DATE, #1707)

- *Scope.* `builder_paths.py` (`CAPTAIN_DOCUMENT_PATHS`, `captain_document_write_refusal`), the eight call sites of AD-1344's rule outside the builder, four AD-1344 tests, `deterministic-ship.md` (invariant 5), tests. Contract `prompts/bf-943-captain-document-write-refusal.md`.
- *D1, D2 (set, roots).* The issue's 17 entries; canonical components; a directory entry names all below it; an absent name is named. Judged below the running checkout (above `constitution_path()`) and the writer's root, each as written and as resolved: `write_file`'s root is `<checkout>/src`. Rejected: more entries (L3); the writer's root alone; any tree; the working directory as a third root (L2).
- *D3 to D6.* One function beside AD-1344's, called after it at its eight sites with each writer's error shape and a constant log line; a hard link to an existing document is found by a scan gated on `st_nlink != 1`; a sibling census (`_GUARDS` stays: it means any one of the rules). Not merged into AD-1344's or BF-911's rules.
- *D8 (severity).* High: nothing between the DM loop and `WriteFileTool.invoke` compares a called tool with the offered set (T4); AD-548's hook is not on `DispatchToolExecutor` (unchanged).
- *Residual.* L1 to L10 of the contract. *Reversal.* Revert the BF-943 commits.
```

**P3-3.** `docs/development/deterministic-ship.md`, invariant 5's known-gaps cell (the SEARCH is the end of that cell's text; PR #1713 does not touch this row).
SEARCH:
```
Work permits are built but not consumed (`tools/work_permits.py:9-13`; owner AD-1348, #1630). |
```
REPLACE:
```
Work permits are built but not consumed (`tools/work_permits.py:9-13`; owner AD-1348, #1630). The agent file writers refuse the Constitution (AD-1344), the loaded config and vault files (BF-911) and, since BF-943 (#1707), the Captain's governance, instruction and manifest files in the running checkout; shell and code execution, MCP servers and agent-designed code are outside that floor (#1523). |
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited (`git grep BF-943` finds no roadmap row).

## 8. What this does NOT change

`builder_write_refusal`, `fix_loop_write_refusal`, `FIX_LOOP_PROTECTED_PATHS`, `constitution_write_refusal`, `protected_write_refusal` and their existing calls; the build lane (`builder.py`, `build_dispatcher.py`, `worktree_manager.py`, `build_pipeline.py`, `routers/build.py`, `copilot_adapter.py`); `swe_harness/policies.py` and `blocked_paths` in `config.py`; `DispatchToolExecutor`, the registry, the rank matrix and the offered set; `run_command`, `run_python`, MCP servers and agent-designed code; the Captain's channels (the HXI config router, git, the editor, `scripts/`); `standing_orders.py` and `config/standing_orders/*`; AD-1346's census rows and every baseline (section 11); `config.py`, the roadmap. OSS only; no dependency.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| 1 | M2 | src/probos/cognitive/builder_paths.py | `len(below) >= len(entry) and all(_document_component(name, expected) for name, expected in zip(below, entry))` | `len(below) == len(entry) and all(...)` | T10 (72), T20 (108), T21 (14), T11, T12, T14, T15, T24 (201 cases) |
| 2 | M2 | src/probos/cognitive/builder_paths.py | `if parts[: len(top)] == top and any(` | `if any(` | T2 (7) |
| 3 | M2 | src/probos/cognitive/builder_paths.py | `roots = [_running_checkout(), writer_root]` | `roots = [writer_root]` | T12, T20 (40), T22, T23, T24 (46 cases) |
| 4 | M2 | src/probos/cognitive/builder_paths.py | `roots = [_running_checkout(), writer_root]` | `roots = [_running_checkout()]` | T12, T20 (40) |
| 5 | M2 | src/probos/cognitive/builder_paths.py | `if _names_a_document(Path(os.path.abspath(target)), [Path(os.path.abspath(r)) for r in roots]):` | `if False:` | T14 |
| 6 | M2 | src/probos/cognitive/builder_paths.py | `if _names_a_document(target.resolve(strict=False), resolved_roots):` | `if False:` | T14, T15, T16 |
| 7 | M2 | src/probos/cognitive/builder_paths.py | `if not stat.S_ISREG(current.st_mode) or current.st_nlink == 1:` | `if True:` | T13 (26), T22 (4), T16 |
| 8 | M2 | src/probos/cognitive/builder_paths.py | `if found.is_dir():` | `if False:` | T13 (12: the directory members) |
| 9 | M2 | src/probos/cognitive/builder_paths.py | `return _captain_document_unverifiable(path, "target", exc)` | `return None` | T16 |
| 10 | M2 | src/probos/cognitive/swe_harness/tools.py | `refused = captain_document_write_refusal(path_text, _PROJECT_ROOT)  # BF-943: edit_file` | `refused = None  # BF-943: edit_file` | T20 (40), T22, T24, T30, T31 (44 cases) |

Run by hand against the patched modules (no pytest), the new file alone (485 cases). **Campaign of record** (base `63cf49cc`; hashes of the LF text, so normalise a CRLF working copy first; git blob id, then sha256): `builder_paths.py` with P2-1 to P2-3 `6df6529158fd` `5d9cd0d9156047f8190445080a59f0d9d5741f77f2d03391b77c6825fc83effc`; `swe_harness/tools.py` with P2-4 to P2-6 `681322dffe3f` `9c39578d459fa01ec38b4a7f2143632ab9adaba6384330abfdb75029f5d44f0a`; `agents/file_writer.py` with P2-7 to P2-9 `b7b7bcf48f2e` `31ba8eec87b3f11b06cd8ad65a7e32fba6139950c30d7bc88866ded17e5ee4f6`; `skill_framework.py` with P2-10 to P2-14 `0d324b990b49` `8229d202653571c7d03f9b7e5d59dff5accf18e9e003931fed59ed6b3b00e2c6`; the new test file with N2-1 applied `ad88725c6923` `e4dd8e05e6a227fcdf61896d692968cbd7906610a2bf403b5e5e4b118042b342`; `tests/test_ad1344_constitution_write_refusal.py` with N1-2 to N1-5 `a1eaf0a9ff48` `e53bf2898126e58388fab4719f2e57617ec484becc7f015bb0d05b33cc1cf5f0` (the new file imports its helpers; N1-2 to N1-5 do not touch them). A Builder whose files equal these does not repeat the table. If `builder_paths.py` or the new test file differs, rerun every row and extra; if only `swe_harness/tools.py` differs, row 10; if only `file_writer.py` differs, the `commit_write` extra; no row mutates `skill_framework.py`. Not tabulated, for the cap, each run once and killed: `if fnmatchcase(name, expected):` to `if name == expected:` (T10 16, T20 24); the short-form `return` of `_document_component` to `return False` (T11 4); the `commit_write` call to `refused = None` (T20 40, T22, T24, T30, T31); the UNC branch of `_document_parts` to `if False:` (T15). Not killed, by design: removing `or current.st_nlink == 1` (a shortcut: the scan finds nothing for an unlinked file either way).

## 10. Recorded limits

- **L1.** A Captain document in another tree (a sibling checkout, a build worktree) reached by an absolute path is not refused, as the issue asks. Reach: any agent with a write tool that knows the path; a worktree's `CLAUDE.md` or `.claude/` instructs a coding agent started there. Options: any tree (D2 row C), a registry of the Captain's trees (new state).
- **L2.** C comes from the location of `standing_orders.py` and `_PROJECT_ROOT` from `tools.py`. In a non-editable install (`Dockerfile:16`, `uv sync --no-dev --no-editable`; `:12-13`, `:25-26` copy `src/` and `config/` to `/app`) both are directories of the environment, not `/app`: `FileWriterAgent` and the office writers are still judged against the working directory (`/app`, `Dockerfile:4`); `write_file` and `edit_file` (W = the environment's `_PROJECT_ROOT`) do not judge an absolute path under `/app`. Read, not run. Option B+ closes it.
- **L3.** Same-class files outside the issue's list stay writable by these writers: `desktop/package.json`, `desktop/package-lock.json`, `Dockerfile`, `docker-compose.yml`, `docker/cowork-base/Dockerfile`, `MANIFEST.in`, `.githooks/`, a `CLAUDE.md` or `AGENTS.md` below the root (Claude Code and Codex read those where they work), `config/skills/` (`SKILL.md` files the catalog scans, `startup/communication.py:708`). Adding one is a line in the tuple and a member in T10. Ranked: instruction files at any depth, manifests and container files, `config/skills/`; a product call, not decided here.
- **L4.** The rule has no actor: a file the Captain asks ProbOS to write in chat reaches these writers and is refused, as the Constitution is. The Captain's own channels are untouched.
- **L5.** Check-then-write is not atomic (AD-1344's residual, `DECISIONS.md:465`): a link made between the check and the write is not seen, and making one needs the shell or code channels (#1523). A filesystem that reports one link for a linked file defeats the identity scan; a document that cannot be listed or examined refuses the write (T16).
- **L6.** Unchanged: shell, code, MCP and agent-designed code (#1523); AD-548's hook is not on `DispatchToolExecutor`, and nothing refuses an unoffered tool at invoke time (section 1: the route T4 shows).
- **L7.** With the AD-546 harness on (off by default) M2 refuses its in-place edits of an entry in the running checkout; a block in its final text still applies in the worktree.
- **L8.** Over-refusal by design: a case variant on a case-sensitive filesystem; a `~digit` name at an entry's position that shares its first two characters (`config/ST~1.md`); an agent's own file under an entry (a scratch repository's `.github/` under the checkout or the working directory).
- **L9.** Not measured: a live vessel, a real model (what it emits for an unoffered tool), a container, and on this host a symlink (`os.symlink` fails with WinError 1314: T14 uses a junction; its symlink form, a symlinked entry and the POSIX case rules are first exercised by the Linux CI); the extended UNC branch is checked by a pure-function line only (T15); `os.link` cases skip where hard links are unavailable.
- **L10.** The issue's line numbers moved (`:1015` is `:1065`, `:1108` is `:1158`, `confinement=` `:476` is `:631`) and its reach cell for `WriteFileTool` is corrected (section 1). The censuses prove names, not reachability: a call under `if False` passes them.

## 11. Verified Against Codebase (2026-11-09, reading tree `D:\ProbOS-worktrees\bf942-build` at `63cf49cc`)

**Run by the Architect, read-only (CPython 3.12.13, win32; scratch in `%TEMP%\bf943-oracle`, outside every repository; `-B`; no pytest runner):**

```
the pairs of 7.1 to 7.3 (4 + 14 + 3) and the new file applied in label order to the LF blobs of HEAD: every SEARCH once; every result compiles; every replacement is ASCII except the 67 box-drawing characters of the new file's two banner comments (AD-1344's test file uses the same banners); the three tracker files' working copies are CRLF throughout
final pass on this file's own text (the reading tree was removed meanwhile; `git show` in `D:\ProbOS`): its 22 blocks parsed and equal to the verified pairs byte for byte; applied as written, stripped, in label order, to the blobs at `63cf49cc` (each SEARCH once at its turn; results equal to the verified ones; M2's results compile) and at `bab8413e` (each SEARCH once; M2's results compile); N1-1's source equals the source the 485 cases ran; N2-1 applies once; each Line of section 9 occurs once, stripped, in M2's patched file; the backticked file:line citations of sections 1 to 3 and 10 were listed with their lines at `63cf49cc` and read against their claims
the patched modules exec'd over the real tree (an import hook gives each its tree path), the 485 cases driven by a stand-in for the fixtures: base 21 guards pass, 464 class cases fail at the assert section 6 names; patched 485 pass; the mutants of section 9 and four more
tests/test_ad1344_constitution_write_refusal.py (147 cases): base 147 pass; patched without N1-2 to N1-5 143 pass and 4 fail (test_write_file_refuses_absolute_paths_and_still_writes_the_neighbours, test_edit_file_refuses_a_hard_link_and_still_edits_the_ship_tier and test_the_swe_tools_judge_the_text_they_write at result.success; test_office_revise_and_update_refuse_a_link_to_the_constitution with PermissionError from create_docx); with them 147 pass on both trees
tests/test_bf911_protected_config_write_refusal.py: 119 pass on both; 11 more writer files (file_writer, office_agents, ad838, ad544, utility_agents, bf961, bf912, bf894, ad152, ad1284, bf830): equal counts on both; 16 cases of four of them error on both for fixtures the stand-in lacks (the driver's limit, not the change's)
SRP of the touched classes (ast, patched): WriteFileTool 90 lines/4 methods, EditFileTool 127/4, FileWriterAgent 163/6, DocxAgent 221/6, PptxAgent 180/4, XlsxAgent 101/3 (triggers 500 and 15); builder_paths.py 484 -> 645 lines, functions only
```

**Absence Verified (2026-11-09)**

```
CLAIM: no BF-943 other than #1707
RUN:   git log --all --grep=BF-943; prompts/bf-943* in each of the 120 directories of D:\ProbOS-worktrees and in D:\ProbOS; gh issue list --state all --search "BF-943 in:title"; git grep -n BF-943 over HEAD and origin/main
FOUND: one commit, 1edb960d (a documents-only research note, 2026-10-30); 0 files; #1707 only; three lines in docs/research (gh-aw-absorption.md:11, :33; reference-projects.md:32), none in the roadmap, PROGRESS.md or DECISIONS.md
HOLDS: yes

CLAIM: AD-548's hook is added once, to the runtime's executor; DispatchToolExecutor is built once
RUN:   rg -n 'add_pre_hook\(|_pre_hooks' src; rg -n --pcre2 '(?<![A-Za-z_])(ToolExecutor|DispatchToolExecutor)\(' src; rg -n 'wire_durable_tool_records' src
FOUND: executor.py:510, :514, :674, :959, and :1485 inside wire_durable_tool_records (:1471; called at agentic_dispatch.py:3044); finalize.py:1890 (blocked paths); constructions at finalize.py:5824 and agentic_dispatch.py:2987
HOLDS: yes

CLAIM: confinement is passed once; nothing refuses an unoffered tool on the DM route
RUN:   rg -n 'confinement=|confine_calls' src; rg -n 'known_tools' src; read agentic_dispatch.py:800-933, :1233, :3600-3611 and tool_manifest.py:317-331
FOUND: agent_work_runner.py:631 (the call), agentic_dispatch.py:1004 (definition) and :3610 (under `if confinement is not None`); known_tools only at agentic_dispatch.py:4368 and dm/reply_value.py; the refusals listed in section 1
HOLDS: yes, by reading (not run: T4 and the orchestrator's probe)

CLAIM: no standing order says who may edit the standing orders; no docs sentence on builder_paths says it; no baseline row is for an edited class or adds a table
RUN:   git grep -n -i -E '(standing order|constitution|directive|CLAUDE\.md|\.github|config/).*(edit|rewrite|modif|amend|write access|may write|not write|must not write)|(edit|rewrite|modif|amend|write access|may write|not write|must not write).*(standing order|constitution|CLAUDE\.md|\.github|config/)' 63cf49cc -- config/standing_orders; git grep -n builder_paths HEAD -- docs; rg -n 'builder_paths|swe_harness|file_writer|skill_framework' over docs/development/*-baseline.yaml, config-profiles.yaml and scripts/check_*.py
FOUND: no line of the 43 files of config/standing_orders pairs those words (exit 1); ship.md:73-82 lists what the crew writes in Ship's Records; standing_orders.py:10 calls the agent tier "(evolvable)"; docs: architecture-reference.md:187, self-maintenance-architecture.md:107 (neither says who may write); baselines: store-baseline.yaml:159 (module skill_framework: its tables only), architecture-baseline.yaml:650 and :897 (SRP rows for AgenticLoop and AgentSkillService), config-profiles.yaml:365 (a key)
HOLDS: yes, for lines that pair those words; the baselines name `skill_framework` only as a module of tables (row 159)

CLAIM: the tests that write under an entry through these writers are four in AD-1344's file
RUN:   git grep -l for the writer and rule names over tests/test_*.py (35 files), for tool-id invocations of write_file (3 more) and for the entries' paths (61 files); the intersection; rg of the entries' segments in the writer files; the files run by hand on both trees (above)
FOUND: the intersection is AD-1344's file, BF-911's (one line, a channel scan) and test_ad548_blocked_paths_policy.py (a hook test: no write); the segments elsewhere are command-policy, ontology and standing_orders_lookup names
HOLDS: yes
```

**Read, not run:** `builder_paths.py:24-110`, `:149-195` (reused from AD-1344's rule: `_canonical`, `_SHORT_NAME`, `_exception_name`, `constitution_path()`, the exact-`str` gate, `resolve(strict=False)`, `os.stat` identity, refusal on a failure; new: the root-relative comparison, the set and glob, the dot-aware short form, the link scan, the extended-length prefix); `swe_harness/tools.py:1020-1235`; `file_writer.py:95-171`; `skill_framework.py:196-285`, `:404-436`, `:536-566`; `standing_orders.py:35`, `:103-115`; `security/file_access.py:562-617`; `tools/registry.py:276-480`; `agentic_dispatch.py:1027-1260`; `native_builder.py:1-210`; `Dockerfile`. **The preflight** (`run_test_gate.py:1088-1128`: `gen_config_reference`, `check_config_profiles`, `check_config_facade`, `gen_ad_ledger`, `check_seam_contracts`, `check_architecture_principles`, `check_store_registry`, `compileall`) is moved only by the ledger, which M3 regenerates: the change adds no config field or read, no table (the store baseline lists tables by module), no class over 500 lines or 15 methods, no layer import (the new imports are stdlib; `standing_orders` is already imported), and no baseline row is for an edited class or adds a table (`store-baseline.yaml:159` lists `skill_framework`'s tables; `architecture-baseline.yaml:650` and `:897` are SRP rows for other classes; the `rg` above). **Not measured:** a live vessel (its data directory is `%LOCALAPPDATA%\ProbOS\data`: none was read); a real model; a container; the Linux CI.

## 12. Prior Art and Blind Spots

- **Internal: adopted.** AD-1344 (the rule's shape, `_canonical`, the exact-`str` gate, resolution and identity, failing closed, the census, T36's channel scan); BF-911 (the same eight sites, the constant log lines, the layout of its tests, the census pairing T33); BF-894 (canonical components); BF-897 (builds stay in a worktree); AD-900 (`directive_store.py`) as the governed route for standing orders; AD-1339's gradient (agent-tier orders are propose-only). **External:** gh-aw's protected files (`docs/research/gh-aw-absorption.md:33`): this is its "absorb, for the runtime writers only".
- **The seven checks of `deterministic-ship.md` section 5.** (1) Owner: yes, `builder_paths`; each writer's call is the commit point. (2) No side door: **no**: shell, code, MCP and agent-designed code (#1523), and other trees (L1); the issue excludes them. (3) Authority and attribution: the check is ordinary code; the refusal records the operation and reason code and **no actor**, because the constant line keeps a path out of the log (D4) and these writers carry no actor. (4) History: yes, a refusal changes nothing (T20 compares the tree). (5) Honest report: the reason names what was refused and the governed routes, P3-3 says what is and is not covered, T20 crosses from the real writers to the tree. (6) Free thinking: the rule meets an agent only where its write would land; the cost is that a change to a document goes through directives or a build (L4). (7) The Captain: no tracked script, hook or workflow names the rule or the set (T5).
- **Blind spots handled.** Each of the eight sites and each shape of path (relative, absolute, `..`, case, trailing dot or space, stream, short form, a real alias, an extended-length path, a hard link, a junction or symlink into a directory, an entry that is itself a link, an absent name, a path that cannot be resolved or examined, a non-`str`); the SWE root being `src`; the build lane and the harness; the Constitution keeping AD-1344's reason; the strict-native context.
- **What discards a correct result.** A correct write refused: any write to an entry (the design), the Captain's chat request (L4), an in-place harness edit (L7), a `~digit` or case-variant neighbour (L8), a write whose link scan cannot list a document (fail closed, T16). A correct result not shown: none found. **Recorded:** L1 to L10.

## 13. Diff Reviewer: properties to verify

1. Each of the eight sites calls `captain_document_write_refusal` after its AD-1344 block and before BF-911's call, with the arguments AD-1344's call has, returns its own error shape and logs the constant line without `refused`; for the Constitution AD-1344's reason is still the one returned.
2. The rule checks the exact-`str` type first; judges the written and the resolved form against C and W (`_running_checkout()`, `writer_root`); refuses an existing regular file with `st_nlink != 1` that is a document; refuses on `OSError`, `RuntimeError` or `ValueError` and swallows nothing else; `CAPTAIN_DOCUMENT_PATHS` is the issue's 17 entries.
3. The diff changes none of `builder_write_refusal`, `fix_loop_write_refusal`, `FIX_LOOP_PROTECTED_PATHS`, `constitution_write_refusal`, `protected_write_refusal`, the build modules or `standing_orders.py`; no tracked script, hook or workflow names the rule or the set (T5); the callers are the eight sites (T30, T31).
4. Of AD-1344's file only N1-2 to N1-5 change, each to a neighbour outside the set with a comment citing BF-943.
5. M1: the file collects on the unfixed tree, imports no BF-943 name, and its 464 class cases fail at their own `assert`; N2-1 removes the marker only. T4 passes on both trees; if it fails, P3-1 says Medium and L6 is rewritten.

## 14. Acceptance criteria

- G1, G2 and G3 pass as stated, and the batch's broad gate is green with a receipt.
- **Acceptance 1 (the issue):** on the base the reproduction runs (G1 with `--runxfail`: an edit of `ship.md`, a creation of `CLAUDE.md` and `.claude/agents/x.md` succeed), and T4 settles the severity.
- **Acceptance 2:** each of the eight sites refuses and still writes a neighbour: six writers for every entry, relative and absolute (T20, T1); `docx_revise` and `xlsx_update` for a file under each of the seven directory entries (T21; a .docx or .xlsx is not a file entry); a hard link through four writers (T22). **Acceptance 3:** a native build still modifies `config/standing_orders/ship.md` in its worktree (AD-1344's T20 and T3). **Acceptance 4:** the census fails for a writer that calls `constitution_write_refusal` without the new rule (T31). **Acceptance 5:** no tracked script, hook or workflow names the rule or the set (T5).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
