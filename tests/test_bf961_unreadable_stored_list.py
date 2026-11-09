"""BF-961 (#1774): a failed or refused read of a bundled agent's stored list never leads to a write.

The real TodoAgent and SchedulerAgent run ``handle_intent`` against a runtime double whose ``intent_bus.broadcast``
returns the answer under test (the seam cases: the three real FileReaderAgent), with ~ moved under ``tmp_path`` and
``commit_write`` recorded. The doubles are the runtime with its bus, and the model; no network. The class holds the cases the unfixed tree fails; the
functions before it pass on both. No BF-961 name is imported.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.agents.file_reader import FileReaderAgent
from probos.agents.file_writer import FileWriterAgent
from probos.agents.utility.organizer_agents import NoteTakerAgent, SchedulerAgent
from probos.agents.utility.productivity_agents import TodoAgent
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.llm_client import MockLLMClient
from probos.types import IntentMessage, IntentResult, LLMRequest, LLMResponse, Priority

NEW = {"text": "new item"}
STORED = json.dumps([{"text": "stored item"}])
KINDS = {  # agent, intent, file, the key its model answer carries the list under, what the model is shown
    "todo": SimpleNamespace(cls=TodoAgent, intent="manage_todo", file="todos.json", key="todos", label="Current todos", what="your todo list"),
    "scheduler": SimpleNamespace(cls=SchedulerAgent, intent="manage_schedule", file="reminders.json", key="reminders", label="Saved reminders", what="your saved reminders"),
}
STATES = {"stored": STORED, "missing": None, "empty": ""}  # what the agent's file holds; None: no file
_ANSWERS = {  # one read_file broadcast: (success, result, error) per answer
    "found": [(True, STORED, None)] * 3,
    "missing": [(False, None, "File not found: x")] * 3,
    "refused": [(False, None, "path is outside every readable root")] * 3,
    "os-error": [(False, None, "[Errno 13] Permission denied: 'x'")],
    "mixed": [(False, None, "File not found: x"), (False, None, "handler failed")],
    "no-content": [(True, None, None)],
    "nobody": [],
}


class _Bus:
    def __init__(self, shape: str) -> None:
        self.shape = shape

    async def broadcast(self, intent: IntentMessage, *args: object, **kwargs: object) -> list[IntentResult]:
        return [IntentResult(intent_id=intent.id, agent_id="reader", success=s, result=r, error=e) for s, r, e in _ANSWERS[self.shape]]


class _Readers:
    """The three real FileReaderAgents of the filesystem pool behind a bus; *runtime* is what BF-944 will hand them."""

    def __init__(self, runtime: object = None) -> None:
        self.agents = [FileReaderAgent(agent_id=f"fr-{i}", runtime=runtime) for i in range(3)]

    async def broadcast(self, intent: IntentMessage, *args: object, **kwargs: object) -> list[IntentResult]:
        answers = [await agent.handle_intent(intent) for agent in self.agents]
        return [answer for answer in answers if answer is not None]


class _Model(MockLLMClient):
    """Answers every request with one text and keeps the requests."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(content=self.text, model="mock", tier=request.tier, tokens_used=1, cached=False, request_id=request.id)


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """~ moved under tmp_path; ``writes`` lists the path of every commit_write call (each is passed on)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert Path.home() == home, "premise: ~ is the temporary home"
    writes: list[str] = []
    real = FileWriterAgent.commit_write

    async def record(path: str, content: str, *, runtime: object = None) -> dict:
        writes.append(path)
        return await real(path, content, runtime=runtime)

    monkeypatch.setattr(FileWriterAgent, "commit_write", staticmethod(record))
    return SimpleNamespace(home=home, tmp=tmp_path, writes=writes)


def _confining(tmp_path: Path) -> SimpleNamespace:
    """A runtime whose read policy admits an unrelated directory and a workspace root, so ~/.probos is outside every readable root."""
    data, allowed = tmp_path / "data", tmp_path / "allowed"
    (data / "workspaces").mkdir(parents=True)
    allowed.mkdir()
    return SimpleNamespace(
        data_dir=data,
        config=SimpleNamespace(
            execution=SimpleNamespace(workspace_root=str(data / "workspaces")),
            security_infra=SimpleNamespace(read_roots=[str(allowed)]),
        ),
    )


async def _round(kind: str, bus: object, scene: SimpleNamespace, stored: str | None):
    """One intent through the real agent: (its IntentResult, the model, the agent's file). ``stored`` None: no file."""
    spec = KINDS[kind]
    target = scene.home / ".probos" / spec.file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    if stored is not None:
        target.write_text(stored, encoding="utf-8")
    model = _Model(json.dumps({"action": "check", spec.key: [NEW]}))
    agent = spec.cls(agent_id=f"{kind}-1", llm_client=model, runtime=SimpleNamespace(intent_bus=bus))
    result = await agent.handle_intent(IntentMessage(intent=spec.intent, params={"action": "add"}))
    return result, model, target


async def _control(kind: str, scene: SimpleNamespace, bus: object) -> None:
    """Premise: a good read reaches the model and its list is written, so 'nothing written' below is not an inert harness."""
    result, model, target = await _round(kind, bus, scene, STORED)
    assert result.success is True and len(model.requests) == 1 and STORED in model.requests[0].prompt, "premise: the list is read"
    assert json.loads(target.read_text(encoding="utf-8")) == [NEW] and len(scene.writes) == 1, "premise: the model's list is written"
    scene.writes.clear()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("state", STATES)
async def test_through_the_real_readers_a_stored_missing_or_empty_file_still_works(scene, kind, state):
    """The seam: the file, the real readers, the agent's read, the model, the write."""
    result, model, target = await _round(kind, _Readers(), scene, STATES[state])
    assert result.success is True and len(model.requests) == 1
    assert (STORED if state == "stored" else f"{KINDS[kind].label}:\n[]") in model.requests[0].prompt
    assert json.loads(target.read_text(encoding="utf-8")) == [NEW] and len(scene.writes) == 1


@pytest.mark.parametrize(("shape", "shown"), [("found", f"Note 'My Note':\n{STORED}"), ("missing", "Note 'My Note' not found.")])
async def test_the_note_agent_reads_as_before(scene, shape, shown):
    agent = NoteTakerAgent(agent_id="note-1", llm_client=_Model(""), runtime=SimpleNamespace(intent_bus=_Bus(shape)))
    obs = await agent.perceive(IntentMessage(intent="manage_notes", params={"action": "read", "title": "My Note"}))
    assert obs["fetched_content"] == shown


async def test_the_reader_still_says_file_not_found_in_its_own_words(tmp_path):
    path = str(tmp_path / "absent.json")
    for intent in ("read_file", "stat_file"):
        answer = await FileReaderAgent(agent_id="fr-0").handle_intent(IntentMessage(intent=intent, params={"path": path}))
        assert (answer.success, answer.error) == (False, f"File not found: {path}")


class TestAFailedReadWritesNothing:
    # BF-961 M1: xfail until M2 builds it (M2 removes this line and the next).
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-961 M2 builds it")

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("shape", ["refused", "os-error", "mixed", "no-content", "nobody"])
    async def test_the_intent_is_refused_before_the_model_and_nothing_is_written(self, scene, kind, shape):
        await _control(kind, scene, _Bus("found"))
        result, model, target = await _round(kind, _Bus(shape), scene, STORED)
        assert result.success is False and result.error == f"Could not read {KINDS[kind].what}; nothing was changed or saved."
        assert model.requests == [] and scene.writes == []
        assert target.read_bytes() == STORED.encode("utf-8")

    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("state", STATES)
    async def test_a_read_the_policy_refuses_writes_nothing(self, scene, kind, state):
        """BF-944's case without BF-944: the readers are built with a runtime whose read_roots omit ~/.probos."""
        await _control(kind, scene, _Readers())
        result, model, target = await _round(kind, _Readers(_confining(scene.tmp)), scene, STATES[state])
        assert result.success is False and result.error == f"Could not read {KINDS[kind].what}; nothing was changed or saved."
        assert model.requests == [] and scene.writes == []
        assert (target.read_bytes() if target.exists() else None) == (None if STATES[state] is None else STATES[state].encode("utf-8"))

    def test_the_guard_is_not_shadowed(self):
        assert TodoAgent.decide is not CognitiveAgent.decide and TodoAgent.decide is SchedulerAgent.decide
