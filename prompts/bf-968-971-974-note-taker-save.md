# Note-taker save: note names stay inside the notes folder, only a save request saves, commit_write replaces in one step -- #1799, #1802, #1805, one batch

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-14
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-14: amendment A1 (section 10a), the repair of review round 1.
**File in the repository:** `prompts/bf-968-971-974-note-taker-save.md`. No commit subject or tracker line of this batch carries an `AD-` or `BF-` token, or this file's name (section 5).
**Status:** ready to build on `origin/main` after #1794 merges. Read on `5275d008`. #1794 edits `routers/chat.py` and its own tests only, so the five files below do not move; the trackers move, but their anchors stay.
**Dependencies:** none in code. **Numbers:** #1799 is BF-968, #1802 is BF-971 and #1805 is BF-974 (`gh issue view`). Nothing is allocated here.
**Builder:** `claude-sonnet-5.5`; at most about 150 tool calls per milestone; focused tests only; search first, then read the range. **Diff Reviewer:** `gpt-6.1-sol` (section 9).
**Estimated tests (expected, not measured):** one new file, `tests/test_note_taker_save.py`, with 39 cases: 27 strict xfail at M1 and 12 controls. Three existing files are edited, each with its reason inline, and no test function is removed.

**Base blobs (`5275d008`).**

| File | Blob | Role |
|---|---|---|
| `src/probos/agents/utility/organizer_agents.py` | `967aee622fd59ab8a89a3a617bd33072013ec993` | edited (M2a, M2b) |
| `src/probos/cognitive/builder_paths.py` | `77cdab7ed020fbf76c28fc3dfebae4478795d0d7` | edited (M2a) |
| `src/probos/agents/file_writer.py` | `b7b7bcf48f2ee5a08c13ecf30c1c6a5f1da7b168` | edited (M2c) |
| `tests/test_utility_agents.py` | `d4900bc77641e447c7ac0cf565eb2858bf81fd14` | edited (M2b) |
| `tests/test_ad1344_constitution_write_refusal.py` | `a1eaf0a9ff48739bf4ab966c11d2e04293f576cb` | edited (M2c) |
| `tests/test_ad1346_admission_file_write_census.py` | `d805ad1ca32e9a0f22bb98e4aa475839f0fc2f0c` | edited (M2c) |
| `PROGRESS.md`, `DECISIONS.md` | `3e87baf3...`, `675bdc29...` | move with #1794's merge; anchors in M3 |

## 1. Problem (re-derived on `5275d008`)

| Issue | Evidence | Verdict |
|---|---|---|
| #1799: save joins the model's name unchecked | `organizer_agents.py:176-179` (`filename = data.get("filename", "untitled.md")`, `path = f"{notes_dir}/{filename}"`, then `_mesh_write_file`); `:43-53` -> `file_writer.py:150-179`: three refusal rules, `mkdir`, `write_text` | Holds |
| #1799: read builds its path from the title | `organizer_agents.py:117-124` (`title.replace(" ", "-").lower()`, `.md` appended, `read_stored_list(..., f"{notes_dir}/{filename}")`) | Holds |
| #1799: on by default | `startup/agent_fleet.py:110` (`("note_taker", "note_taker", 2)`) | Holds |
| #1802: act saves on the model's word | `organizer_agents.py:164-185`. The requested action is read only in `perceive` (`:113`) | Holds |
| #1802: decide's dict reaches act | `cognitive_agent.py:7650` (`decision = await self.decide(observation)`), `:7813` (`await self.act(action_decision)`). The procedure fallback `:7989-7991` calls `act` without `decide` | Holds |
| #1805: in-place write | `file_writer.py:171-172`; `stored_list.py:62-69` reads an empty success as FOUND | Holds |
| #1805: callers | `organizer_agents.py:52`, `productivity_agents.py:111`, `runtime.py:4994` | Holds |
| *New:* two censuses pin the old write | `test_ad1344_constitution_write_refusal.py:761` (row `".write_text"` for `commit_write`; a stale row fails T35, `:888-894`). `test_ad1346_admission_file_write_census.py:170-187` (counts of each point name over `src`) | Required edits (P2c-3, P2c-4) |
| *New:* one unit case calls `act` without the new key | `test_utility_agents.py:782-800` (`test_note_taker_persists_to_disk`) | Required edit (P2b-3) |

## 2. Solution and decisions

- **M1** adds `tests/test_note_taker_save.py`. It drives the real agent and the real `commit_write`, with `~` moved under `tmp_path`. Each built case is strict xfail per issue, and each M2 milestone adds its own issue to `_BUILT`.
- **M2a (#1799):** `note_file(notes_dir, name) -> str | None` in `organizer_agents.py`, used by both save and read:
  1. Each run of characters outside `[A-Za-z0-9._-]` becomes `-`, and leading dots and dashes are stripped.
  2. An empty result is refused. Otherwise `.md` is appended if missing.
  3. A Windows device name is refused, through the new public `builder_paths.is_reserved_device_name` (the builder's `_RESERVED` rule at `:80`, compared in `_canonical` form).
  4. Backstop: the resolved file's parent must equal the resolved folder.

  Save answers `success False` when the name is refused; read shows "not found".
  Compatibility, read only: when the reduced name is refused or its read answers MISSING, read tries `legacy_note_file`, the name the base read (`title.replace(" ", "-").lower()`, `.md` appended). That name is refused if it holds `/`, `\`, `:` or a control character, and otherwise passes the same device-name and backstop checks. A note saved under such a name before this change is still found by its title; save always writes the reduced name.
- **M2b (#1802):** `decide` returns `{**super_decision, "requested_action": <params action, stripped, lower-cased, default "list">}`. It returns a new dict, so a cached decision is never mutated. `act` saves only when `requested_action == "save"`. Otherwise it returns the model's text, writes nothing and logs at INFO.
- **M2c (#1805):** `commit_write` writes a sibling `.<16 hex>.tmp` file (21 characters, whatever the target's name; A1) and replaces the target with `os.replace`.
  - The temp file: created exclusively by `open(temp, "x", encoding="utf-8")` (`O_CREAT|O_EXCL`, mode `0o666` under umask, no raw descriptor; A1), the existing target's mode copied onto it, written, flushed and fsynced.
  - The target is `realpath(p)`, so a link is still written through, not replaced.
  - On any exception the temp file is unlinked and the old failure shape returned.
  - The write stays inside `commit_write`, so the AD-1344 census keeps a mechanically checked guarded row.
- **Rejected or deferred:**
  - Refusing any name that is not already one component: a save titled "Q3/Q4 plan" would fail. Rejected.
  - A `.bak` copy: an extra visible file with no retention rule. Rejected.
  - Using `mkstemp`: it creates the file `0o600`, so new notes and lists would change mode. Rejected.
  - A shared atomic-write helper for the other `os.replace` sites: considered and deferred (#1805).
  - Rewiring `builder_write_refusal:500` to the new predicate: equivalent, but it would touch a security boundary. Deferred.

## 3. Milestones and gates

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`, run from the repository root, always with `-n 0 -p no:randomly`.

**The Builder's gates (focused tests only):**
- **M0:** record `--collect-only -q` counts for every existing file named in G2a to G2c.
- **G1 (M1):** `PY -m pytest tests/test_note_taker_save.py -q -n 0 -p no:randomly`.
  - **Expected (not measured):** POSIX gives **12 passed, 27 xfailed**. A Windows host without symlink rights gives **10 passed, 26 xfailed, 3 skipped**.
  - Then set `$env:NOTE_TAKER_SAVE_RUNXFAIL = "1"`, run the file alone, and `Remove-Item Env:NOTE_TAKER_SAVE_RUNXFAIL`. Every xfail case fails at its own `assert`: none at an import, a fixture or a call.
  - An XPASS is a FAIL; report it to the Architect.
- **G2a (M2a):**
  - Tests: the new file, `tests/test_bf894_builder_write_boundary.py`, `tests/test_bf961_unreadable_stored_list.py`, `tests/test_utility_agents.py` and `tests/test_bf911_protected_config_write_refusal.py`.
  - Expected: the new file has 6 xfailed and the rest passed or skipped. Every other file has 0 failed and its M0 count.
- **G2b (M2b):** the new file, `tests/test_utility_agents.py`, `tests/test_bf961_unreadable_stored_list.py` and `tests/test_ad686_oracle_semantic_tier.py`. Expected: the new file has 2 xfailed.
- **G2c (M2c):**
  - Tests: the new file, `tests/test_file_writer.py`, `tests/test_ad1344_constitution_write_refusal.py`, `tests/test_ad1346_admission_file_write_census.py`, `tests/test_bf911_protected_config_write_refusal.py`, `tests/test_bf943_captain_document_write_refusal.py`, `tests/test_bf961_unreadable_stored_list.py`, `tests/test_utility_agents.py`, `tests/test_ad1284_consensus_gate_reachability.py` and `tests/test_bf912_escalation_approval_is_not_a_commit.py`.
  - Then `PY -P scripts/check_architecture_principles.py --check`.
  - Expected: the new file has 0 xfailed; everything else is clean.
- **G3 (M3):** `PY -P scripts/gen_ad_ledger.py`, then `PY -P scripts/gen_ad_ledger.py --check`, then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`. No AD or BF number moves. Any changed number row is a hard stop for the Architect.

**The orchestrator's steps:** the oracle (every SEARCH applies exactly once, in label order), the mutation campaign (section 7), then once: `PY scripts/run_test_gate.py --label note-taker-save --receipt logs/gates/note-taker-save.receipt.json`.

**Harness rule.** No source change to make a test pass, no new skip, no loosened assertion. If an expected count differs, including the census numbers in P2c-4, stop and report to the Architect.

## 4. The contract

The SEARCH text is LF, ASCII, starts at a line start and matches exactly once in its file, once the earlier blocks for that file have been applied in label order. A label names its file by full path. The non-ASCII lines of the edited sources are `organizer_agents.py:3`, `:197` and `file_writer.py:1`; all lie outside every SEARCH.

### M1

**N1-1.** New file `tests/test_note_taker_save.py`. It imports only names that exist on the base. The predicate is read with `getattr`, so on the base that case fails at an assert, not at import.

```python
"""The note-taker saves only for a save request, only inside its notes folder; commit_write replaces in one step.

#1799: a model-chosen note name, or a requested title, becomes one file directly in ~/.probos/notes, or none.
#1802: act() saves only when the request was a save, whatever the model answers.
#1805: FileWriterAgent.commit_write writes a sibling temporary file and replaces the target in one step.

The real NoteTakerAgent runs with ~ moved under ``tmp_path``, a bus double that no reader answers (or, for the
older-name reads, one that answers from disk) and a model double
that answers one text; every write goes through the real ``commit_write``. Synthetic fixtures only. A case marked
``until_built("#N")`` failed on the base at its own assert; the milestone that builds #N adds it to ``_BUILT``, after
which the marker does nothing. ``NOTE_TAKER_SAVE_RUNXFAIL=1`` runs every case plainly.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.agents.file_reader import FILE_NOT_FOUND_MARK
from probos.agents.file_writer import FileWriterAgent
from probos.agents.utility.organizer_agents import NoteTakerAgent
from probos.cognitive import builder_paths
from probos.cognitive.llm_client import MockLLMClient
from probos.types import IntentMessage, IntentResult, LLMRequest, LLMResponse, Priority

_BUILT: frozenset[str] = frozenset()


def until_built(issue: str) -> Any:
    """Strict xfail at an assert until *issue*'s milestone adds it to ``_BUILT``."""
    if issue in _BUILT or os.environ.get("NOTE_TAKER_SAVE_RUNXFAIL") == "1":
        return lambda func: func
    return pytest.mark.xfail(raises=AssertionError, strict=True)


_BODY = "# A note\nline two\n"
_LOGGER = "probos.agents.utility.organizer_agents"


class _Model(MockLLMClient):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text

    async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
        return LLMResponse(content=self.text, model="mock", tier=request.tier, tokens_used=1, cached=False, request_id=request.id)


class _Bus:
    """No reader answers; the path of every read_file broadcast is kept."""

    def __init__(self) -> None:
        self.read_paths: list[str] = []

    async def broadcast(self, intent: IntentMessage, *args: object, **kwargs: object) -> list[IntentResult]:
        if intent.intent == "read_file":
            self.read_paths.append(intent.params["path"])
        return []


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert Path.home() == home, "premise: ~ is the temporary home"
    return home


def _notes_dir() -> str:
    return os.path.expanduser(NoteTakerAgent._NOTES_DIR)


def _agent(reply: dict | str, bus: _Bus | None = None) -> NoteTakerAgent:
    text = reply if isinstance(reply, str) else json.dumps(reply)
    return NoteTakerAgent(agent_id="note-1", llm_client=_Model(text), runtime=SimpleNamespace(intent_bus=bus or _Bus()))


def _save_reply(filename: str) -> dict:
    return {"action": "save", "filename": filename, "content": _BODY, "message": "saved"}


async def _save(filename: str) -> dict:
    """act() as handle_intent calls it for a save request."""
    reply = _save_reply(filename)
    return await _agent(reply).act({"requested_action": "save", "llm_output": json.dumps(reply)})


def _in_notes(home: Path) -> list[str]:
    notes = home / ".probos" / "notes"
    return sorted(entry.name for entry in notes.iterdir()) if notes.is_dir() else []


def _outside_notes(home: Path) -> list[str]:
    notes = home / ".probos" / "notes"
    return sorted(str(p.relative_to(home)) for p in home.rglob("*") if p.is_file() and notes not in p.parents)


_REDUCED = [
    ("../x.md", "x.md"), ("..\\x.md", "x.md"), ("a/../../x.md", "a-..-..-x.md"), ("/abs/evil.md", "abs-evil.md"),
    ("C:x.md", "C-x.md"), ("C:\\x\\evil.md", "C-x-evil.md"), ("Q3/Q4 plan", "Q3-Q4-plan.md"),
]


@until_built("#1799")
@pytest.mark.parametrize(("name", "reduced"), _REDUCED, ids=[
    "dot-dot", "backslash", "inner-dot-dot", "absolute", "drive-relative", "drive-absolute", "slash-in-title"])
async def test_a_model_chosen_name_becomes_one_file_inside_notes(home, name, reduced):
    result = await _save(name)
    assert _outside_notes(home) == []
    assert result["success"] is True and _in_notes(home) == [reduced]
    assert (home / ".probos" / "notes" / reduced).read_text(encoding="utf-8") == _BODY


async def test_a_plain_name_saves_where_it_always_did(home):
    assert await _save("my-note.md") == {"success": True, "result": "saved"}
    assert _in_notes(home) == ["my-note.md"] and _outside_notes(home) == []


@until_built("#1799")
@pytest.mark.parametrize("name", ["NUL", "nul.md"])
async def test_a_windows_device_name_is_refused(home, name):
    result = await _save(name)
    assert result["success"] is False
    assert _in_notes(home) == [] and _outside_notes(home) == []


@pytest.mark.parametrize("name", ["../"])
async def test_a_name_with_nothing_left_is_refused(home, name):
    result = await _save(name)
    assert result["success"] is False
    assert _in_notes(home) == [] and _outside_notes(home) == []


# On the base "./" saves a file named notes where the folder belongs (pathlib drops the ".").
@until_built("#1799")
async def test_a_dot_slash_name_is_refused(home):
    result = await _save("./")
    assert result["success"] is False
    assert _in_notes(home) == [] and _outside_notes(home) == []


@until_built("#1799")
def test_the_reserved_name_predicate_is_the_builders_rule():
    predicate = getattr(builder_paths, "is_reserved_device_name", None)
    assert callable(predicate)
    assert [predicate(n) for n in ("CON", "con.md", "Nul", "COM1.md", "lpt9", "AUX .md", "nul.md.")] == [True] * 7
    assert [predicate(n) for n in ("console.md", "my-note.md", "com10.md", "nulls.md")] == [False] * 4


@until_built("#1799")
async def test_a_note_linked_out_of_the_folder_is_refused(home):
    notes = home / ".probos" / "notes"
    notes.mkdir(parents=True)
    outside = home / "outside.md"
    outside.write_bytes(b"outside\n")
    try:
        (notes / "link.md").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("this host cannot create a symbolic link")
    result = await _save("link.md")
    assert result["success"] is False
    assert outside.read_bytes() == b"outside\n"


class _DiskBus(_Bus):
    """A reader that answers read_file from disk as FileReaderAgent does: the text, or its "not found" answer."""

    async def broadcast(self, intent: IntentMessage, *args: object, **kwargs: object) -> list[IntentResult]:
        await super().broadcast(intent)
        if intent.intent != "read_file":
            return []
        path = intent.params["path"]
        if os.path.isfile(path):
            text = Path(path).read_text(encoding="utf-8")
            return [IntentResult(intent_id=intent.id, agent_id="reader", success=True, result=text)]
        return [IntentResult(intent_id=intent.id, agent_id="reader", success=False, error=f"{FILE_NOT_FOUND_MARK}{path}")]


async def _read(title: str, bus: _Bus | None = None) -> tuple[_Bus, dict]:
    bus = bus or _Bus()
    obs = await _agent("", bus).perceive(IntentMessage(intent="manage_notes", params={"action": "read", "title": title}))
    return bus, obs


@until_built("#1799")
@pytest.mark.parametrize(("title", "reduced"), [("../x", "x.md"), ("..\\x", "x.md"), ("a/../../x", "a-..-..-x.md")],
                         ids=["dot-dot", "backslash", "inner-dot-dot"])
async def test_a_dot_dot_title_reads_only_inside_notes(home, title, reduced):
    bus, _obs = await _read(title)
    assert bus.read_paths == [f"{_notes_dir()}/{reduced}"]


async def test_a_title_reads_the_file_it_always_read(home):
    bus, _obs = await _read("My Note")
    assert bus.read_paths == [f"{_notes_dir()}/my-note.md"]


@until_built("#1799")
async def test_a_title_with_nothing_left_reads_nothing(home):
    bus, obs = await _read("../")
    assert bus.read_paths == [] and obs["fetched_content"] == "Note '../' not found."


def _notes(home: Path) -> Path:
    notes = home / ".probos" / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    return notes


_OLDER = [("Caf\u00e9", "caf\u00e9.md"), ("Bob's plan", "bob's-plan.md"), ("C++ notes", "c++-notes.md")]


@pytest.mark.parametrize(("title", "older"), _OLDER, ids=["accent", "apostrophe", "plus"])
async def test_a_note_saved_before_the_reduction_is_read_by_its_title(home, title, older):
    (_notes(home) / older).write_text(_BODY, encoding="utf-8")
    _bus, obs = await _read(title, _DiskBus())
    assert obs["fetched_content"] == f"Note '{title}':\n{_BODY}"


@until_built("#1799")
async def test_the_reduced_name_is_read_before_the_older_one(home):
    notes = _notes(home)
    (notes / "caf\u00e9.md").write_text("older\n", encoding="utf-8")
    (notes / "caf-.md").write_text(_BODY, encoding="utf-8")
    _bus, obs = await _read("Caf\u00e9", _DiskBus())
    assert obs["fetched_content"] == f"Note 'Caf\u00e9':\n{_BODY}"


@until_built("#1799")
@pytest.mark.parametrize(("title", "reduced"), [("../outside", "outside.md"), ("C:x", "c-x.md"), ("x.md:s", "x.md-s.md")],
                         ids=["dot-dot", "drive-relative", "stream"])
async def test_an_older_name_that_is_not_one_file_in_notes_is_not_read(home, title, reduced):
    _notes(home)
    (home / ".probos" / "outside.md").write_text(_BODY, encoding="utf-8")
    bus, obs = await _read(title, _DiskBus())
    assert bus.read_paths == [f"{_notes_dir()}/{reduced}"]
    assert obs["fetched_content"] == f"Note '{title}' not found."


@until_built("#1799")
async def test_an_unreadable_reduced_name_does_not_fall_back_to_the_older_one(home):
    bus, _obs = await _read("Caf\u00e9")
    assert bus.read_paths == [f"{_notes_dir()}/caf-.md"]


async def test_a_missing_plain_title_is_read_once(home):
    bus, obs = await _read("My Note", _DiskBus())
    assert bus.read_paths == [f"{_notes_dir()}/my-note.md"] and obs["fetched_content"] == "Note 'My Note' not found."


_NOT_A_SAVE = {"list": {"action": "list"}, "read": {"action": "read", "title": "n"},
               "search": {"action": "search", "query": "n"}, "no-action": {}}


@until_built("#1802")
@pytest.mark.parametrize("params", list(_NOT_A_SAVE.values()), ids=list(_NOT_A_SAVE))
async def test_a_request_that_is_not_a_save_writes_nothing(home, params, caplog):
    caplog.set_level(logging.INFO, logger=_LOGGER)
    result = await _agent(_save_reply("n.md")).handle_intent(IntentMessage(intent="manage_notes", params=params))
    assert result is not None and result.success is True
    assert _in_notes(home) == [] and _outside_notes(home) == []
    assert any("not a save" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("action", ["save", " Save "])
async def test_a_save_request_still_saves(home, action):
    params = {"action": action, "title": "kept"}
    result = await _agent(_save_reply("kept.md")).handle_intent(IntentMessage(intent="manage_notes", params=params))
    assert result is not None and result.success is True
    assert _in_notes(home) == ["kept.md"]


@until_built("#1805")
async def test_a_failed_replace_keeps_the_old_bytes_and_leaves_no_temp_file(tmp_path, monkeypatch):
    target = tmp_path / "list.json"
    target.write_bytes(b'[{"text": "stored"}]\n')

    def _refuse(src: Any, dst: Any) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", _refuse)
    result = await FileWriterAgent.commit_write(str(target), "[]")
    assert result == {"success": False, "error": "simulated replace failure"}
    assert target.read_bytes() == b'[{"text": "stored"}]\n'
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["list.json"]


async def test_a_write_gives_the_bytes_write_text_gives_and_the_same_keys(tmp_path):
    target = tmp_path / "out" / "note.md"
    target.parent.mkdir()
    target.write_bytes(b"old\n")
    reference = tmp_path / "reference.md"
    reference.write_text(_BODY, encoding="utf-8")
    result = await FileWriterAgent.commit_write(str(target), _BODY)
    assert result == {"success": True, "path": str(target.resolve()), "size": len(_BODY)}
    assert target.read_bytes() == reference.read_bytes()
    assert sorted(entry.name for entry in target.parent.iterdir()) == ["note.md"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
async def test_the_mode_is_kept_or_is_what_write_text_gives(tmp_path):
    kept, new, reference = tmp_path / "kept.md", tmp_path / "new.md", tmp_path / "reference.md"
    kept.write_text("old\n", encoding="utf-8")
    kept.chmod(0o600)
    reference.write_text("x\n", encoding="utf-8")
    for path in (kept, new):
        assert (await FileWriterAgent.commit_write(str(path), "x\n"))["success"] is True
    assert stat.S_IMODE(kept.stat().st_mode) == 0o600
    assert stat.S_IMODE(new.stat().st_mode) == stat.S_IMODE(reference.stat().st_mode)


async def test_a_write_through_a_link_replaces_the_linked_file(tmp_path):
    real, link = tmp_path / "real.md", tmp_path / "link.md"
    real.write_text("old\n", encoding="utf-8")
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("this host cannot create a symbolic link")
    assert (await FileWriterAgent.commit_write(str(link), "new\n"))["success"] is True
    assert link.is_symlink() and real.read_text(encoding="utf-8") == "new\n"


@until_built("#1805")
async def test_a_save_request_naming_dot_dot_lands_in_notes_through_one_replace(home, monkeypatch):
    """The cross-seam case: request -> decide -> act -> note_file -> the real commit_write -> one replace in notes/."""
    real_replace = os.replace
    moves: list[tuple[str, str]] = []

    def _spy(src: Any, dst: Any) -> None:
        moves.append((os.fspath(src), os.fspath(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _spy)
    reply = {"action": "save", "filename": "../../escape.md", "content": _BODY, "message": "saved"}
    params = {"action": "save", "title": "escape"}
    result = await _agent(reply).handle_intent(IntentMessage(intent="manage_notes", params=params))
    assert result is not None and result.success is True
    notes = home / ".probos" / "notes"
    assert _outside_notes(home) == [] and _in_notes(home) == ["escape.md"]
    assert (notes / "escape.md").read_text(encoding="utf-8") == _BODY
    home_real = home.resolve()
    assert [(Path(dst).resolve(), Path(src).name.startswith(".escape.md.") and src.endswith(".tmp"))
            for src, dst in moves if home_real in Path(dst).resolve().parents] == [((notes / "escape.md").resolve(), True)]
```

**How the built cases fail on the base (expected):**
- N1: the file lands outside `notes/`, or in a subfolder, or under its literal name, so `_in_notes != [reduced]`.
- Device names: the save succeeds (the device or a file), so `success is True`.
- Predicate: `callable(None)` is false.
- Link: the write goes through the link.
- Reads: the read path is the raw join.
- Not-a-save: `notes/n.md` is written.
- Failed replace: `success True` (`os.replace` is never called).
- Chain: `escape.md` lands in `~`.

### M2a (#1799)

**P2a-1** (`src/probos/cognitive/builder_paths.py`: the public predicate)
SEARCH:
```
def _canonical(part: str) -> str:
    """One component in the form a case-insensitive filesystem compares it."""
    return _HFS_IGNORABLE.sub("", part).rstrip(" .").upper()
```
REPLACE:
```
def _canonical(part: str) -> str:
    """One component in the form a case-insensitive filesystem compares it."""
    return _HFS_IGNORABLE.sub("", part).rstrip(" .").upper()


def is_reserved_device_name(part: str) -> bool:
    """BF-968 (#1799): whether one path component is a Windows device name (``NUL``, ``con.md``, ``AUX .txt``),
    compared in canonical form: the rule ``builder_write_refusal`` applies to each component, for other writers."""
    return _RESERVED.match(_canonical(part)) is not None
```

**P2a-2** (`src/probos/agents/utility/organizer_agents.py`: imports)
SEARCH:
```
import json
import logging
import os
import time
from typing import Any

from probos.agents.utility.stored_list import UnreadableListGuard, read_stored_list
from probos.cognitive.cognitive_agent import CognitiveAgent
```
REPLACE:
```
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from probos.agents.utility.stored_list import ReadStatus, UnreadableListGuard, read_stored_list
from probos.cognitive.builder_paths import is_reserved_device_name
from probos.cognitive.cognitive_agent import CognitiveAgent
```

**P2a-3** (`src/probos/agents/utility/organizer_agents.py`: `note_file`)
SEARCH:
```
# ------------------------------------------------------------------
# NoteTakerAgent
# ------------------------------------------------------------------

class NoteTakerAgent(_BundledMixin, CognitiveAgent):
```
REPLACE:
```
# ------------------------------------------------------------------
# Note file names (BF-968)
# ------------------------------------------------------------------

#: A run of characters a note's file name does not keep; each run becomes one "-".
_NOTE_NAME_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
#: A character that keeps an older note name from being read: a separator, the drive or stream colon, a control.
_LEGACY_NOTE_NAME_REFUSED = re.compile(r"[/\\:\x00-\x1f\x7f]")


def _file_in(notes_dir: str, name: str) -> str | None:
    """``f"{notes_dir}/{name}"`` when *name* is not a device name and its real parent is the real *notes_dir*, else None."""
    if is_reserved_device_name(name):
        return None
    try:
        inside = Path(notes_dir, name).resolve().parent == Path(notes_dir).resolve()
    except (OSError, RuntimeError):  # a link loop: no file is named
        inside = False
    return f"{notes_dir}/{name}" if inside else None


def note_file(notes_dir: str, name: str) -> str | None:
    """The path of the one file *name* names directly in *notes_dir*, or None when it names none.

    BF-968 (#1799): *name* comes from the model (save) or from the requested title (read). Each run of characters
    outside ``[A-Za-z0-9._-]`` becomes "-", leading dots and dashes go and ".md" is appended when missing, so the
    result is one component ("Q3/Q4 plan" -> "Q3-Q4-plan.md", "../x.md" -> "x.md"). An empty result and a Windows
    device name are refused. Backstop: the resolved file must sit directly in the resolved folder, which also refuses a
    note that is a link out of the folder.
    """
    safe = _NOTE_NAME_UNSAFE.sub("-", name).lstrip(".-")
    if not safe:
        return None
    if not safe.endswith(".md"):
        safe += ".md"
    return _file_in(notes_dir, safe)


def legacy_note_file(notes_dir: str, name: str) -> str | None:
    """The path of a note an older build saved under *name* as given, or None. Read only: no save calls it.

    BF-968 (#1799): before the reduction a note kept the name the model chose, and a title was read as
    ``title.replace(" ", "-").lower()`` with ".md" appended. The read path tries that name only when the reduced name is
    refused or missing, so a note saved earlier under an accented letter, an apostrophe or a plus sign is still found by
    its title. A name holding a separator, a colon (``C:x.md`` is drive-relative, ``x.md:s`` a stream) or a control
    character is refused; any other name passes the device-name check and the backstop ``note_file`` uses.
    """
    legacy = name if name.endswith(".md") else name + ".md"
    if _LEGACY_NOTE_NAME_REFUSED.search(legacy):
        return None
    return _file_in(notes_dir, legacy)


# ------------------------------------------------------------------
# NoteTakerAgent
# ------------------------------------------------------------------

class NoteTakerAgent(_BundledMixin, CognitiveAgent):
```

**P2a-4** (`src/probos/agents/utility/organizer_agents.py`: read)
SEARCH:
```
            if title:
                # Sanitize filename
                filename = title.replace(" ", "-").lower()
                if not filename.endswith(".md"):
                    filename += ".md"
                # BF-961: a note that cannot be read shows as not found, as before; what the model then answers can still save a note (L5)
                content = (await read_stored_list(self._runtime, f"{notes_dir}/{filename}")).text
```
REPLACE:
```
            if title:
                # BF-968 (#1799): the title names one file directly in the notes folder, or none (shown as not found)
                requested = str(title).replace(" ", "-").lower()
                path = note_file(notes_dir, requested)
                read = await read_stored_list(self._runtime, path) if path is not None else None
                if read is None or read.status is ReadStatus.MISSING:
                    # a note saved before the reduction keeps the name the base read it by (L1)
                    legacy = legacy_note_file(notes_dir, requested)
                    if legacy is not None and legacy != path:
                        read = await read_stored_list(self._runtime, legacy)
                # BF-961: a note that cannot be read shows as not found, as before; what the model then answers can still save a note (L5)
                content = read.text if read is not None else ""
```

**P2a-5** (`src/probos/agents/utility/organizer_agents.py`: save)
SEARCH:
```
                if isinstance(data, dict) and data.get("action") == "save":
                    notes_dir = os.path.expanduser(self._NOTES_DIR)
                    filename = data.get("filename", "untitled.md")
                    content = data.get("content", "")
                    path = f"{notes_dir}/{filename}"
                    written = await _mesh_write_file(self._runtime, path, content)
```
REPLACE:
```
                if isinstance(data, dict) and data.get("action") == "save":
                    notes_dir = os.path.expanduser(self._NOTES_DIR)
                    filename = str(data.get("filename") or "untitled.md")
                    path = note_file(notes_dir, filename)  # BF-968: one file directly in the notes folder
                    if path is None:
                        logger.warning("BF-968: NoteTakerAgent refused a note name that names no file in the notes folder")
                        return {"success": False, "error": f"Failed to save note: {filename[:80]!r} is not a usable note name"}
                    content = data.get("content", "")
                    written = await _mesh_write_file(self._runtime, path, content)
```

**P2a-6** (`tests/test_note_taker_save.py`)
SEARCH:
```
_BUILT: frozenset[str] = frozenset()
```
REPLACE:
```
_BUILT: frozenset[str] = frozenset({"#1799"})
```

### M2b (#1802)

**P2b-1** (`src/probos/agents/utility/organizer_agents.py`: decide, and the check in act)
SEARCH:
```
    async def act(self, decision: dict) -> dict:
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}

        llm_output = decision.get("llm_output", "")

        # Handle save operations
        if self._runtime:
            try:
                data = json.loads(llm_output)
                if isinstance(data, dict) and data.get("action") == "save":
```
REPLACE:
```
    async def decide(self, observation: dict) -> dict:
        """BF-971 (#1802): carry the requested action to ``act``, which saves only for a save request."""
        decision = await super().decide(observation)
        params = observation.get("params") or {}
        return {**decision, "requested_action": str(params.get("action") or "list").strip().lower()}

    async def act(self, decision: dict) -> dict:
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}

        llm_output = decision.get("llm_output", "")

        # Handle save operations
        if self._runtime:
            try:
                data = json.loads(llm_output)
                if isinstance(data, dict) and data.get("action") == "save":
                    if decision.get("requested_action") != "save":
                        # BF-971: the model answered "save" to a request that was not a save; nothing is written
                        logger.info(
                            "BF-971: NoteTakerAgent declined a save: the request was %r, not a save",
                            str(decision.get("requested_action"))[:40],
                        )
                        return {"success": True, "result": llm_output}
```

**P2b-2** (`src/probos/agents/utility/organizer_agents.py`: the read comment that BF-971 makes stale)
SEARCH:
```
                # BF-961: a note that cannot be read shows as not found, as before; what the model then answers can still save a note (L5)
```
REPLACE:
```
                # BF-961: a note that cannot be read shows as not found, as before (BF-971: a read request never saves a note)
```

**P2b-3** (`tests/test_utility_agents.py`)
SEARCH:
```
        decision = {
            "llm_output": json.dumps({
                "action": "save",
                "filename": "test-note.md",
```
REPLACE:
```
        decision = {
            # #1802: the note-taker saves only for a save request; decide() sets this key.
            "requested_action": "save",
            "llm_output": json.dumps({
                "action": "save",
                "filename": "test-note.md",
```

**P2b-4** (`tests/test_note_taker_save.py`)
SEARCH:
```
_BUILT: frozenset[str] = frozenset({"#1799"})
```
REPLACE:
```
_BUILT: frozenset[str] = frozenset({"#1799", "#1802"})
```

### M2c (#1805)

**P2c-1** (`src/probos/agents/file_writer.py`: imports)
SEARCH:
```
import logging
from pathlib import Path
from typing import Any
```
REPLACE:
```
import contextlib
import logging
import os
import secrets
import stat
from pathlib import Path
from typing import Any
```

**P2c-2** (`src/probos/agents/file_writer.py`: the write)
SEARCH:
```
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {
```
REPLACE:
```
            p.parent.mkdir(parents=True, exist_ok=True)
            # BF-974 (#1805): never truncate in place. Write a sibling temporary file and replace the target in one
            # step, so a crash mid-write leaves the old file whole. The target is the real path the old in-place
            # write followed, so a link is still written through, not replaced.
            target = Path(os.path.realpath(p))
            temp = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
            try:
                kept_mode: int | None = stat.S_IMODE(os.stat(target).st_mode)
            except FileNotFoundError:
                kept_mode = None
            # The os.fdopen text layer below translates newlines once, as write_text does.
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                if kept_mode is not None:
                    os.chmod(temp, kept_mode)
                os.replace(temp, target)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(temp)  # the temporary file this call created; the error is raised on
                raise
            return {
```

**P2c-3** (`tests/test_ad1344_constitution_write_refusal.py`: T35's rows)
SEARCH:
```
    ("src/probos/agents/file_writer.py", "FileWriterAgent.commit_write", ".write_text"): _GUARDED,
```
REPLACE:
```
    # #1805: commit_write replaces its target from a sibling temporary file; os.open and os.fdopen are not census writes.
    ("src/probos/agents/file_writer.py", "FileWriterAgent.commit_write", "os.replace"): _GUARDED,
    ("src/probos/agents/file_writer.py", "FileWriterAgent.commit_write", "os.unlink"): "the temporary sibling this call created, removed when its write or replace fails",
```

**P2c-4** (`tests/test_ad1346_admission_file_write_census.py`: WF1's counts; expected, from `_file_write` at `tests/fixtures/ad1346_file_write_census.py:83-101`)
SEARCH:
```
        "write_text": 59,
        "write_bytes": 7,
        "unlink": 66,
        "rmtree": 13,
        "copy2": 2,
        "copyfile": 1,
        "copytree": 1,
        "replace": 24,
        "rename": 2,
        "open": 16,
        "fdopen": 10,
```
REPLACE:
```
        # #1805: commit_write's one-step write: write_text -1; unlink, replace, open (O_CREAT), fdopen ("w") +1 each.
        "write_text": 58,
        "write_bytes": 7,
        "unlink": 67,
        "rmtree": 13,
        "copy2": 2,
        "copyfile": 1,
        "copytree": 1,
        "replace": 25,
        "rename": 2,
        "open": 17,
        "fdopen": 11,
```
`len(found) == 73` and the kinds count do not change: `file_writer.py` is already a row (`fixtures/ad1346_file_write_census.py:164`). If the measured counter differs from these values, stop and report to the Architect.

**P2c-5** (`tests/test_note_taker_save.py`)
SEARCH:
```
_BUILT: frozenset[str] = frozenset({"#1799", "#1802"})
```
REPLACE:
```
_BUILT: frozenset[str] = frozenset({"#1799", "#1802", "#1805"})
```

### M3: trackers and ledger

Replace `DATE` with M3's date. No line carries an `AD-` or `BF-` token or this contract's file name.

**P3-1** (`PROGRESS.md`). The anchor is the title line and the blank line after it; #1794's entry stays below this one.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**The note-taker saves only for a save request and only inside its notes folder, and a committed write replaces its file in one step (DATE), #1799 #1802 #1805.**
- **Base.** The note-taker joined the model's file name to `~/.probos/notes` unchecked, so a `..` name wrote any file the process could write, and a `..` title read a `.md` file outside the folder. It saved whenever the model answered "save", whatever the request. `FileWriterAgent.commit_write` truncated then wrote in place, so a crash between the two left an empty file, which the stored-list reader takes for an empty list.
- **Change.** `note_file` reduces a name to one component: each run outside `[A-Za-z0-9._-]` becomes `-`, leading dots and dashes go, and `.md` is appended. It refuses an empty result, a Windows device name (`builder_paths.is_reserved_device_name`, the builder's rule made public) and any file whose real parent is not the real folder; save and read both use it. `decide` carries the requested action to `act`, which saves only for a save request and logs a declined save at INFO. `commit_write` writes a uniquely named sibling temporary file (created exclusively, mode kept, flushed and synced) and replaces the target in one step, removing the temporary file on any failure. A new test file drives the real agent and the real write with a temporary home, including one case from a save request to a single replace inside the folder. Two write-site censuses and one unit case are updated, each with its reason inline. Refs #1799, #1802, #1805.

```

**P3-2** (`DECISIONS.md`). The anchor is the heading below, at line 1796 on `5275d008`. #1794's entry is inserted before it too, so this entry lands after #1794's.
SEARCH:
```
### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```
REPLACE:
```
### The note-taker saves only for a save request and only inside its notes folder; a committed write replaces its file in one step (DATE, #1799, #1802, #1805)

- *Scope.* `agents/utility/organizer_agents.py` (`note_file`; `NoteTakerAgent.decide`; the save and read paths), `cognitive/builder_paths.py` (`is_reserved_device_name`), `agents/file_writer.py` (`commit_write`'s write); one new test file; three existing test files updated with inline reasons.
- *G1 (the name).* Reduce to one component, then a real-path containment backstop. A note saved earlier under a name the reduction changes is still read by its title: the reduced name first, then the earlier name when it is one plain file in the folder. A save writes only the reduced name. Rejected: refusing any name that is not already one plain component, which fails a legitimate save titled "Q3/Q4 plan"; keeping Unicode letters, which still loses apostrophes and plus signs and lets look-alike letters name distinct notes.
- *G2 (the request).* `act` saves only when the requested action is `save`. A save request whose intent omits the action no longer saves.
- *G3 (the write).* A sibling temporary file and `os.replace`, inside `commit_write`, so the write-site census keeps its guarded row. Rejected: a `.bak` copy (an extra visible file with no retention rule) and `mkstemp` (new files would be created private). Deferred: one shared atomic-write helper for the other replace sites.
- *Residual.* L1 to L6 of the contract. *Reversal.* Revert the batch's commits in reverse order; files written meanwhile stay valid.

### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```

**Ledger.** Run G3. No AD or BF number moves. The roadmap Bug Tracker is not edited.

## 5. Commit messages

Every body ends with its `Refs` paragraph; the committing agent's trailer paragraph comes after it. No subject contains an `AD-` or `BF-` token. No message uses a closing keyword in any form: close, closes, closed, fix, fixes, fixed, resolve, resolves or resolved. Write "real path", not "resolved path".
- Contract (the orchestrator's): `Note-taker save (#1799, #1802, #1805): contract for note names inside the notes folder, saves only on a save request, and a one-step replace in commit_write`, then `Refs #1799, #1802, #1805.`
- M1: `Note-taker save M1: tests for note names, save requests and the one-step write, xfail until built (#1799, #1802, #1805)`, then `Refs #1799, #1802, #1805.`
- M2a: `Note-taker save M2a: a note name becomes one file inside the notes folder, or none (#1799)`, then `Refs #1799.`
- M2b: `Note-taker save M2b: only a save request saves a note (#1802)`, then `Refs #1802.`
- M2c: `Note-taker save M2c: commit_write replaces its file in one step, and the two write-site censuses say why (#1805)`, then `Refs #1805.`
- M3: `Note-taker save M3: trackers and ledger (#1799, #1802, #1805)`, then `Refs #1799, #1802, #1805.`

With `BASE` = the `origin/main` commit the batch is built on, both scans must print nothing:
- `git log --format=%B BASE..HEAD | rg -n -i "\bClos[e]s\b"`
- `git log --format=%B BASE..HEAD | rg -n -i "\b(clos[e][sd]?|fix(e[sd])?|resolv[e][sd]?)\b"`

The orchestrator closes the three issues after the gate.

## 6. Recorded limits

- **L1 (#1799).** Letters outside ASCII are lost in a saved name (`cafe` with an accent becomes `caf-.md`). A note saved before this change under such a name is still read by its title through `legacy_note_file`, unless that name holds `/`, `\`, `:` or a control character. A save that names it writes a new file under the reduced name, which the title then reads; the older file stays and still shows in the list. Name length is not capped; an over-long name fails at the OS, and save answers failure.
- **L2 (#1799).** A note file that is a link out of the folder is refused on save and shows as not found on read. A notes folder that is itself a link is followed. The folder is not a sandbox against links a user places inside it.
- **L3 (#1802).** A save request whose decomposed intent omits `action` no longer saves. The procedure fallback (`cognitive_agent.py:7989-7991`) calls `act` without `decide`, so a save there is declined, which is the safe direction.
- **L4 (#1805).** The parent directory is not fsynced. A hard crash between the write and the replace leaves a hidden `.tmp` sibling, which is never read as the list. So does a failure inside `open` after it has created the file, because `open` stands before the `try` that removes the file. With concurrent writers the last one wins, as before.
- **L5 (#1805, Windows).** A read-only target fails as before, and its temporary copy, made read-only, may remain. A replace onto a file another process holds open fails where an in-place write might have succeeded.
- **L6.** Mutation rows 6, 15 and 16 can be killed only where symlinks or POSIX modes exist, row 14 only on Windows, and row 24 only where the host holds a 255-character name under `tmp_path`. Row 17 is removed (an equivalent mutant). Record each row that cannot be measured on the host as such; do not treat it as killed.
- **L7 (#1805, A1).** The temporary name is 21 characters, so a target whose name is shorter gets a temporary path longer than its own by up to the difference. On a Windows host without long paths, a target whose full path lies within that margin of 260 fails where the base wrote. Any random sibling name has this cost for short names, and the one-step replace needs a sibling.

## 7. Mutation rows (each line occurs once, stripped, in its file after A1; expected, not measured)

| # | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| 1 | organizer | `safe = _NOTE_NAME_UNSAFE.sub("-", name).lstrip(".-")` | `safe = name` | N1 (all), reads dot-dot (all), chain |
| 2 | same | same | `safe = _NOTE_NAME_UNSAFE.sub("-", name)` | N1 dot-dot, backslash, absolute; empty-name; dot-slash; read-nothing |
| 3 | same | `if not safe:` | `if False:` | empty-name; dot-slash; read-nothing |
| 4 | same | `if not safe.endswith(".md"):` | `if False:` | N1 slash-in-title; reads dot-dot |
| 5 | same | `if is_reserved_device_name(name):` | `if False:` | device-name (both) |
| 6 | same | `inside = Path(notes_dir, name).resolve().parent == Path(notes_dir).resolve()` | `inside = True` | link-out (symlink hosts) |
| 7 | same | rows 1 and 6 together (#1799's named mutation) | | N1, reads dot-dot, chain |
| 8 | builder_paths | `return _RESERVED.match(_canonical(part)) is not None` | `return False` | device-name, predicate |
| 9 | organizer | `if decision.get("requested_action") != "save":` | `if False:` | not-a-save (all four) |
| 10 | same | `return {**decision, "requested_action": str(params.get("action") or "list").strip().lower()}` | `return {**decision, "requested_action": str(params.get("action") or "list")}` | save-still-saves ` Save ` |
| 11 | same | same | `return {**decision, "requested_action": "save"}` | not-a-save (all four) |
| 12 | file_writer | `os.replace(temp, target)` | `p.write_text(content, encoding="utf-8")` (#1805's named mutation) | failed-replace, write-bytes, chain |
| 13 | same | `os.unlink(temp)  # the temporary file this call created; the error is raised on` | `pass` | failed-replace |
| 14 | same | `handle = open(temp, "x", encoding="utf-8")` | `handle = open(temp, "x", encoding="utf-8", newline="")` (A1) | write-bytes (Windows only) |
| 15 | same | `os.chmod(temp, kept_mode)` | `pass` | mode (POSIX) |
| 16 | same | `target = Path(os.path.realpath(p))` | `target = p` | link-write (symlink hosts) |
| 17 | removed | equivalent mutant: the O_BINARY flag changed no byte written through os.fdopen (oracle, Windows, 2026-11-14), so the flag was removed from P2c-2 | | |
| 18 | file_writer | `handle = open(temp, "x", encoding="utf-8")` | `"x"` -> `"w"` (A1) | taken-name |
| 19 | organizer | `if read is None or read.status is ReadStatus.MISSING:` | `if read is None:` | older-name (all three) |
| 20 | same | same | `if True:` | reduced-first; no-fallback |
| 21 | same | same | `if read is None or read.status is not ReadStatus.FOUND:` | no-fallback |
| 22 | same | `if legacy is not None and legacy != path:` | `if legacy is not None:` | plain-miss-once |
| 23 | same | `if _LEGACY_NOTE_NAME_REFUSED.search(legacy):` | `if False:` | older-name-refused drive-relative, stream (dot-dot is also refused by the backstop); older-name-C1 (all three) |
| 24 | file_writer | `temp = target.with_name(f".{secrets.token_hex(8)}.tmp")` | `temp = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")` (A1, F1) | 255-name (hosts that hold the name) |
| 25 | organizer | `_LEGACY_NOTE_NAME_REFUSED = re.compile(r"[/\\:\x00-\x1f\x7f-\x9f]")` | `_LEGACY_NOTE_NAME_REFUSED = re.compile(r"[/\\:\x00-\x1f\x7f]")` (A1, F3) | older-name-C1 (all three) |

## 8. What this does NOT change

- **Source:**
  - `_mesh_write_file` and `_mesh_list_dir`, `SchedulerAgent`, `TodoAgent`;
  - `FileWriterAgent.act` (the proposal) and its three refusal rules;
  - `submit_write_with_consensus` (`runtime.py:4994`, a caller and not edited);
  - `builder_write_refusal` (`:500` keeps `_RESERVED.match` directly);
  - `read_stored_list` and `UnreadableListGuard`;
  - the other `os.replace` sites;
  - `perceive`'s list and search branches.
- **Config:** no key and no model.
- **Elsewhere:** `ui/`; the commercial overlay; every tracker except `PROGRESS.md`, `DECISIONS.md` and the ledger pair; the roadmap Bug Tracker.

## 9. Diff Reviewer (`gpt-6.1-sol`): properties to verify

Name the consumer for each property and confirm it accepts the change.

1. **#1799.** For any string, `note_file` returns `None` or `f"{notes_dir}/{c}"`, where `c`:
   - holds only `[A-Za-z0-9._-]`;
   - starts with neither a dot nor a dash and ends `.md`;
   - is not a device name;
   - has a real parent equal to the real folder.

   `legacy_note_file` returns `None` or `f"{notes_dir}/{c}"`, where `c` holds no `/`, `\`, `:` or control character, ends `.md`, is not a device name and has a real parent equal to the real folder. Only the read path calls it, and only after the reduced name is refused or answers MISSING; no save reaches it.

   **Consumers:** `_mesh_write_file` -> `FileWriterAgent.commit_write` (`organizer_agents.py:43-53`, `file_writer.py:150`) on save, and `read_stored_list` (`stored_list.py:38`) on read. Both receive the same string shape as before.
2. **#1802.** Every path from the model's JSON to `_mesh_write_file` in `NoteTakerAgent.act` passes the `requested_action == "save"` check. **Consumer:** `CognitiveAgent.handle_intent` (`cognitive_agent.py:7650` `decide`, `:7813` `act`) carries the key. Confirm that the fallback at `:7989-7991` declines a save.
3. **#1805.** On every exit after `mkdir`, either the target was replaced whole and no temp file remains, or the target is untouched and the temp file was removed (L4 and L5 excepted). A temporary name already taken fails the write and removes nothing. No raw descriptor exists, and the temp file's handle is closed before any unlink or replace. The temporary name is `.<16 hex>.tmp` whatever the target's name (A1). The result dict keeps its old keys and shapes. **Consumers:** the three callers (`organizer_agents.py:52`, `productivity_agents.py:111`, `runtime.py:4994`) and the stored-list reader (`stored_list.py:54-69`).
4. **Censuses.** The changed rows and counts follow the scanners (`test_ad1344...:837-851`, `fixtures/ad1346_file_write_census.py:83-101`); no row is loosened.
5. **Paperwork.** The text is ASCII, and the tracker lines and subjects carry no `AD-` or `BF-` token.

## 10. Acceptance criteria

- **#1799:**
  - `../x.md`, `..\x.md`, `a/../../x.md`, an absolute path, `C:x.md` and `C:\x\evil.md` each become one file inside `notes/` with a real `HOME`.
  - A device name or an empty name is refused, and a link out of the folder is refused.
  - A `..` title reads only inside `notes/`.
  - A note saved under an older name (an accented letter, an apostrophe, a plus sign) is still read by its title. The reduced name is read first, and an older name holding a separator, a colon or a control character (C0, DEL or C1 U+0080 to U+009F; A1) is never read.
  - `my-note.md` still saves to `notes/my-note.md`.
  - Rows 1+6 together fail the tests.
- **#1802:**
  - `list`, `read`, `search` and a request with no action write nothing when the model answers `save`, and the decline is logged at INFO.
  - A save request still writes.
  - Row 9 fails the not-a-save cases.
- **#1805:**
  - With `os.replace` failing, the result is `success False`, the old bytes are kept and no temp file remains.
  - A normal write gives the bytes `write_text` gives and the same keys.
  - The mode is kept (POSIX).
  - Row 12 fails the failed-replace case.
  - A1: a target whose name is 255 characters is written and read back with no leftover, where the host holds the name. A temporary name already taken fails the write and removes nothing. A failed sync keeps the old bytes and leaves no temp file.
- **The chain case passes.** It runs a save request with a `..` filename from `handle_intent` through to one replace into `notes/` and leaves no temp file.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 10a. Amendment A1: review round 1 (2026-11-14)

Round 1 (`gpt-6.1-sol`) found three defects on the M2c head `0b7d69d4`, and the orchestrator reproduced each. A1 repairs all three in one commit after M2c. Blocks A1-1 to A1-8 apply after P2c-5, in label order. The code blocks of P2a (the legacy-name class), P2c-2, P2c-3, P2c-4 and M1's chain assertion stay as M2a, M2c and M1 built them; A1 supersedes the lines it replaces. The prose A1 made false is edited in place: section 2 (M2c), L4, L6, L7, section 7, property 3 and the acceptance criteria.

| Finding | Reach | Decision |
|---|---|---|
| F1 (P2, regression) | ordinary | Fixed (A1-1). The temporary name is `.<16 hex>.tmp`, 21 characters whatever the target's, so every name the host holds is written (the base `.<name>.<16 hex>.tmp` failed at 234 to 255 characters). A bounded prefix of the target's name is rejected: the name is never read back, so the prefix adds nothing. L7 records the path-length cost for short names. |
| F2 (P2, regression) | injected only | Fixed (A1-1), because it is a regression against the base. `open(temp, "x", encoding="utf-8")` creates the file exclusively with no raw descriptor. Closing the descriptor in an `except` around `os.fdopen` is rejected: a real failure inside `io.open` closes it already, so that close could hit another thread's descriptor. `open` stands before the `try`, so a taken name removes nothing this call did not create; L4 records the one gap. |
| F3 (P3, predates) | ordinary | Fixed (A1-2). The class is `[/\\:\x00-\x1f\x7f-\x9f]`, which covers every character of Unicode category Cc. "Control character" in section 2, L1 and property 1 means that category. U+00A0 is not a control and is still read. |

**Commit.** Subject `Note-taker save A1: a constant-length temporary name, no raw descriptor, C1 controls refused (#1799, #1805)`, then `Refs #1799, #1805.` Both scans of section 5 print nothing: no message uses the word "fixed", even in a compound, because the second scan matches it at a hyphen.

**Gate GA1 (focused; expected, not measured).** `PY -m pytest tests/test_note_taker_save.py tests/test_ad1344_constitution_write_refusal.py tests/test_ad1346_admission_file_write_census.py tests/test_file_writer.py tests/test_bf961_unreadable_stored_list.py -q -n 0 -p no:randomly -rs`, then `PY -P scripts/check_architecture_principles.py --check`. Expect 0 failed; the new file gains 6 cases (255-name 1, older-name-C1 3, taken-name 1, failed-sync 1). On a host with long paths enabled, the 255-name case passes and does not skip. WF1's counter changes only `fdopen` (11 -> 10); T35 gains one `_GUARDED` row, for `open`. If another count differs, stop and report to the Architect.

**Mutation campaign.** It runs once, on the A1 head, as the campaign of record (section 7, rows 12 to 16, 18 and 23 to 25 among them).

**A1-1** (`src/probos/agents/file_writer.py`: the temporary file)
SEARCH:
```
            temp = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
            try:
                kept_mode: int | None = stat.S_IMODE(os.stat(target).st_mode)
            except FileNotFoundError:
                kept_mode = None
            # The os.fdopen text layer below translates newlines once, as write_text does.
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
```
REPLACE:
```
            # #1805 A1: a fixed-length name (21 characters), whatever the length of the target's name.
            temp = target.with_name(f".{secrets.token_hex(8)}.tmp")
            try:
                kept_mode: int | None = stat.S_IMODE(os.stat(target).st_mode)
            except FileNotFoundError:
                kept_mode = None
            # "x" creates the file exclusively and leaves no raw descriptor to leak. It is opened before the try below,
            # so a name already taken removes nothing this call did not create. Its text layer translates newlines once,
            # as write_text does.
            handle = open(temp, "x", encoding="utf-8")
            try:
                with handle:
```

**A1-2** (`src/probos/agents/utility/organizer_agents.py`: the C1 controls)
SEARCH:
```
_LEGACY_NOTE_NAME_REFUSED = re.compile(r"[/\\:\x00-\x1f\x7f]")
```
REPLACE:
```
_LEGACY_NOTE_NAME_REFUSED = re.compile(r"[/\\:\x00-\x1f\x7f-\x9f]")
```

**A1-3** (`tests/test_ad1344_constitution_write_refusal.py`: T35's `open` row)
SEARCH:
```
    # #1805: commit_write replaces its target from a sibling temporary file; os.open and os.fdopen are not census writes.
    ("src/probos/agents/file_writer.py", "FileWriterAgent.commit_write", "os.replace"): _GUARDED,
```
REPLACE:
```
    # #1805: commit_write creates a sibling temporary file (open "x") and replaces its target with it; both are guarded.
    ("src/probos/agents/file_writer.py", "FileWriterAgent.commit_write", "open"): _GUARDED,
    ("src/probos/agents/file_writer.py", "FileWriterAgent.commit_write", "os.replace"): _GUARDED,
```

**A1-4** (`tests/test_ad1346_admission_file_write_census.py`: WF1's counts)
SEARCH:
```
        # #1805: commit_write's one-step write: write_text -1; unlink, replace, open (O_CREAT), fdopen ("w") +1 each.
        "write_text": 58,
        "write_bytes": 7,
        "unlink": 67,
        "rmtree": 13,
        "copy2": 2,
        "copyfile": 1,
        "copytree": 1,
        "replace": 25,
        "rename": 2,
        "open": 17,
        "fdopen": 11,
```
REPLACE:
```
        # #1805: commit_write's one-step write: write_text -1; unlink, replace and open (its "x" create) +1 each.
        "write_text": 58,
        "write_bytes": 7,
        "unlink": 67,
        "rmtree": 13,
        "copy2": 2,
        "copyfile": 1,
        "copytree": 1,
        "replace": 25,
        "rename": 2,
        "open": 17,
        "fdopen": 10,
```

**A1-5** (`tests/test_note_taker_save.py`: imports)
SEARCH:
```
import os
import stat
from pathlib import Path
```
REPLACE:
```
import os
import re
import secrets
import stat
from pathlib import Path
```

**A1-6** (`tests/test_note_taker_save.py`: older-name-C1)
SEARCH:
```
@until_built("#1799")
async def test_an_unreadable_reduced_name_does_not_fall_back_to_the_older_one(home):
```
REPLACE:
```
@until_built("#1799")
@pytest.mark.parametrize("control", ["\x80", "\x85", "\x9f"], ids=["U+0080", "U+0085", "U+009F"])
async def test_an_older_name_holding_a_c1_control_is_not_read(home, control):
    """Review round 1, F3: a C1 control (U+0080 to U+009F) is a control character, so the older name is refused."""
    title = f"x{control}y"
    (_notes(home) / f"{title}.md").write_text(_BODY, encoding="utf-8")
    bus, obs = await _read(title, _DiskBus())
    assert bus.read_paths == [f"{_notes_dir()}/x-y.md"]
    assert obs["fetched_content"] == f"Note '{title}' not found."


@until_built("#1799")
async def test_an_unreadable_reduced_name_does_not_fall_back_to_the_older_one(home):
```

**A1-7** (`tests/test_note_taker_save.py`: 255-name, taken-name, failed-sync)
SEARCH:
```
@until_built("#1805")
async def test_a_save_request_naming_dot_dot_lands_in_notes_through_one_replace(home, monkeypatch):
```
REPLACE:
```
async def test_a_target_whose_name_is_255_characters_is_written(tmp_path):
    """Review round 1, F1: the temporary name adds nothing to the target's, so any name the host holds is written."""
    target = tmp_path / ("n" * 252 + ".md")
    try:
        target.write_text("old\n", encoding="utf-8")
    except OSError:
        pytest.skip("this host cannot create a 255-character name here")
    result = await FileWriterAgent.commit_write(str(target), _BODY)
    assert result == {"success": True, "path": str(target.resolve()), "size": len(_BODY)}
    assert target.read_text(encoding="utf-8") == _BODY
    assert sorted(entry.name for entry in tmp_path.iterdir()) == [target.name]


@until_built("#1805")
async def test_a_taken_temporary_name_fails_the_write_and_removes_nothing(tmp_path, monkeypatch):
    """Review round 1, F2: the temporary file is created exclusively; a name already taken is not this call's."""
    target, taken = tmp_path / "list.json", tmp_path / f".{'0' * 16}.tmp"
    target.write_bytes(b'[{"text": "stored"}]\n')
    taken.write_bytes(b"not this call's\n")
    monkeypatch.setattr(secrets, "token_hex", lambda nbytes: "0" * (2 * nbytes))
    result = await FileWriterAgent.commit_write(str(target), "[]")
    assert result["success"] is False
    assert target.read_bytes() == b'[{"text": "stored"}]\n' and taken.read_bytes() == b"not this call's\n"
    assert sorted(entry.name for entry in tmp_path.iterdir()) == sorted([target.name, taken.name])


@until_built("#1805")
async def test_a_failed_sync_keeps_the_old_bytes_and_leaves_no_temp_file(tmp_path, monkeypatch):
    """Review round 1, F2: a failure while the temporary file is open closes it, so it is removed (on Windows too)."""
    target = tmp_path / "list.json"
    target.write_bytes(b'[{"text": "stored"}]\n')

    def _refuse(fd: int) -> None:
        raise OSError("simulated sync failure")

    monkeypatch.setattr(os, "fsync", _refuse)
    result = await FileWriterAgent.commit_write(str(target), "[]")
    assert result == {"success": False, "error": "simulated sync failure"}
    assert target.read_bytes() == b'[{"text": "stored"}]\n'
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["list.json"]


@until_built("#1805")
async def test_a_save_request_naming_dot_dot_lands_in_notes_through_one_replace(home, monkeypatch):
```

**A1-8** (`tests/test_note_taker_save.py`: the chain case pins the fixed-length name and its folder)
SEARCH:
```
    assert [(Path(dst).resolve(), Path(src).name.startswith(".escape.md.") and src.endswith(".tmp"))
            for src, dst in moves if home_real in Path(dst).resolve().parents] == [((notes / "escape.md").resolve(), True)]
```
REPLACE:
```
    # A1: the temporary name is a dot, 16 hex digits and ".tmp", beside the target.
    assert [(Path(dst).resolve(), Path(src).parent.resolve() == notes.resolve()
             and re.fullmatch(r"\.[0-9a-f]{16}\.tmp", Path(src).name) is not None)
            for src, dst in moves if home_real in Path(dst).resolve().parents] == [((notes / "escape.md").resolve(), True)]
```

## 11. Verified Against Codebase (2026-11-14, read-only tree `D:\ProbOS-worktrees\next-read2` at `origin/main` `5275d00874799d68536fef2a7ff27c7bc44cda65`)

```
organizer_agents.py:43-53 _mesh_write_file -> FileWriterAgent.commit_write(path, content, runtime=runtime)
organizer_agents.py:67-71 "# NoteTakerAgent" header; class NoteTakerAgent(_BundledMixin, CognitiveAgent)
organizer_agents.py:106 _NOTES_DIR = "~/.probos/notes"; :113 action = obs.get("params", {}).get("action", "list")
organizer_agents.py:117-124 read path (title.replace(" ", "-").lower(); f"{notes_dir}/{filename}")
organizer_agents.py:164-189 act; :170 "# Handle save operations"; :176 filename = data.get("filename", "untitled.md"); :178 path = f"{notes_dir}/{filename}"
organizer_agents.py:273 SchedulerAgent.act (a second "async def act", so P2b-1's SEARCH includes :170)
file_writer.py:5-7 imports; :150 commit_write; :159-170 three refusals; :171-172 mkdir, write_text
builder_paths.py:80 _RESERVED; :83-85 _canonical; :500 _RESERVED.match(_canonical(part))
stored_list.py:38 read_stored_list; :49 broadcast read_file params {"path": path}; :62-69 empty success -> FOUND
stored_list.py:25-28 ReadStatus FOUND/MISSING/FAILED; :70-71 MISSING only when every answer is the reader's not-found; no answer -> FAILED
file_reader.py:16 FILE_NOT_FOUND_MARK = "File not found: "; :19-24 is_file_not_found; :147, :173 the reader's not-found error
types.py:58-66 IntentMessage(intent, params, ..., id); :78-85 IntentResult(intent_id, agent_id, success, result, error)
organizer_agents.py:116-128 read path: title -> one read_stored_list -> fetched_content "Note '<title>':\n" or "not found."
cognitive_agent.py:3773 decide; :7650 decide; :7813 act(action_decision); :7984-7991 fallback act; :13106 cache off by default
startup/agent_fleet.py:110 ("note_taker", "note_taker", 2)
productivity_agents.py:111 commit_write; runtime.py:4994 commit_write
test_utility_agents.py:782-800 test_note_taker_persists_to_disk (act without requested_action)
test_ad1344_constitution_write_refusal.py:749-751 write sets; :761 commit_write ".write_text" row; :837-851 _write_primitive; :888-894 new/stale
test_ad1346_admission_file_write_census.py:167 len 73; :170-187 counter; fixtures/ad1346_file_write_census.py:42 os {replace,rename,remove,link,write}; :48 OPENS {open, fdopen}; :92-93 os.open with O_CREAT; :164 file_writer.py row
test_bf961_unreadable_stored_list.py:87-103 HOME-move pattern; :74-84 _Model; :157-160 note read "My Note"
test_bf943_captain_document_write_refusal.py:521-527 file_writer.py must not spell stat.FILE_ATTRIBUTE_/IO_REPARSE_TAG_ (S_IMODE is neither)
scripts/gen_ad_ledger.py:210 reads a line only when it starts with AD-/BF-/AD /BF
scripts/check_architecture_principles.py:187-188 srp-size is per class (500 lines, 15 methods)
```

**Absence verified (2026-11-14).**
- **Claim:** none of `is_reserved_device_name`, `def note_file`, `requested_action` or `NOTE_TAKER_SAVE` exists. **Run:** Grep over the tree. **Found:** none. **Holds.**
- **Claim:** none of `legacy_note_file`, `_LEGACY_NOTE_NAME_REFUSED`, `def _file_in` or `_DiskBus` exists. **Run:** Grep `legacy_note_file|_LEGACY_NOTE_NAME_REFUSED|def _file_in\b|_DiskBus` over the tree (2026-11-14). **Found:** none. **Holds.**
- **Claim:** the new test file and this contract do not exist yet. **Run:** Glob `tests/test_note_taker*.py`, `prompts/bf-968*`, `prompts/*note-taker*`. **Found:** none. **Holds.**
- **Claim:** no test pins the read comment that P2b-2 changes. **Run:** Grep `tests` for `can still save a note|organizer_agents\.py|title\.replace`. **Found:** only `test_bf911...:960` (a caller row for `_mesh_write_file`, unchanged). **Holds.**
- **Claim:** nothing in `tests` patches `Path.write_text` around `commit_write`. **Run:** Grep `(setattr|patch)\(.*write_text|Path\.write_text`. **Found:** `test_bf898:671-683` (the fix loop) and `test_knowledge_store.py:333-349` (`skills/wanted.json`); neither reaches `commit_write`. **Holds.**
- **Claim:** `architecture-baseline.yaml` has no row for the three source files. **Run:** Grep `file_writer|organizer_agents|builder_paths`. **Found:** none. **Holds.**
