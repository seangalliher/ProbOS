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
import re
import secrets
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

_BUILT: frozenset[str] = frozenset({"#1799", "#1802", "#1805"})


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
    # A1: the temporary name is a dot, 16 hex digits and ".tmp", beside the target.
    assert [(Path(dst).resolve(), Path(src).parent.resolve() == notes.resolve()
             and re.fullmatch(r"\.[0-9a-f]{16}\.tmp", Path(src).name) is not None)
            for src, dst in moves if home_real in Path(dst).resolve().parents] == [((notes / "escape.md").resolve(), True)]
