"""AD-1200: real consumer seams and pinned no-instructions compatibility."""

from __future__ import annotations

import copy
import asyncio
import hashlib
import json
import re
import sys
from dataclasses import FrozenInstanceError, asdict, fields
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.builder import BuildSpec
from probos.cognitive.swe_harness.native_builder import NativeBuilderHarness
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop
from probos.cognitive.swe_harness.tool_call import (
    InstructionToolCallResult, TextBlock, ToolCallRequest, ToolCallResult, ToolUseBlock,
)
from probos.cognitive.swe_harness.tools import InstructionToolResult, register_native_swe_tools
from probos.repository_instructions import InstructionObservation
from probos.tools.executor import ToolExecutor
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission, ToolResult
from probos.tools.registry import ToolRegistry
from probos.types import LLMRequest, LLMResponse

_ROOT = Path(__file__).resolve().parents[1]
_GOLDEN = _ROOT / "tests" / "fixtures" / "ad1200_no_instructions_golden.json"
_BASE = "3df0f351520605effdbc2be9a49a72ad1a201127"
_AGENT = "ad1200-fixture-agent"
_JSON_STRING = re.compile(r'"(?:\\.|[^"\\])*"')


def _assert_source_provenance() -> int:
    loaded = {
        name: Path(module.__file__).resolve()
        for name, module in tuple(sys.modules.items())
        if (name == "probos" or name.startswith("probos."))
        and getattr(module, "__file__", None)
    }
    assert loaded
    assert all(path.is_relative_to(_ROOT / "src") for path in loaded.values()), loaded
    return len(loaded)


@pytest.fixture(scope="session", autouse=True)
def _candidate_provenance(request: pytest.FixtureRequest) -> Any:
    _assert_source_provenance()
    yield
    count = _assert_source_provenance()
    reporter = request.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(f"AD-1200 provenance: {count} loaded ProbOS modules under {_ROOT / 'src'}")


class _FakeLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        self.requests.append(copy.deepcopy(request))
        assert self.responses, "the real request seam ran more times than scripted"
        return self.responses.pop(0)


class _FakeAttachmentStore:
    def __init__(self) -> None:
        self.blobs: list[bytes] = []

    async def write(
        self, content_hash: str, blob: bytes, mime: str, *, origin: str = ""
    ) -> Path:
        assert hashlib.sha256(blob).hexdigest() == content_hash
        self.blobs.append(blob)
        return Path("fixture-attachments") / content_hash


def _text(text: str = "done") -> LLMResponse:
    return LLMResponse(content=text, content_blocks=[TextBlock(text)], tokens_used=7)


def _read(path: Path, tool: str = "read_file", *, call_id: str = "fixture-call") -> LLMResponse:
    key = "path" if tool == "read_file" else "file_path"
    return LLMResponse(
        content="",
        tokens_used=7,
        content_blocks=[
            ToolUseBlock(ToolCallRequest(
                name=tool, arguments={key: str(path)}, id=call_id, timestamp=123.0,
            )),
        ],
    )


def _runtime(root: Path, *, structured: bool = False) -> SimpleNamespace:
    permissions = ToolPermissionStore()
    registry = ToolRegistry()
    registry.set_permission_store(permissions)
    runtime = SimpleNamespace(
        data_dir=root / "instance",
        config=SimpleNamespace(
            security_infra=SimpleNamespace(read_roots=[str(root)]),
            execution=SimpleNamespace(workspace_root=str(root / "workspaces")),
            agentic_dispatch=SimpleNamespace(enabled=True),
            agentic_loop=SimpleNamespace(
                structured_tool_messages=structured,
                tool_trace_output_max_chars=2000,
            ),
        ),
        tool_registry=registry,
        tool_permission_store=permissions,
        attachment_store=_FakeAttachmentStore(),
        emit_event=None,
    )
    assert register_native_swe_tools(registry, runtime) == 12
    return runtime


def _repo(root: Path, name: str = "project") -> tuple[Path, Path]:
    repo = root / name
    (repo / ".git").mkdir(parents=True)
    source = repo / "src" / "widget.py"
    source.parent.mkdir()
    source.write_text("alpha\nbeta\n", encoding="utf-8")
    return repo, source


async def _native(
    runtime: SimpleNamespace, llm: _FakeLLM, cwd: str, *, paths: bool = True,
) -> dict[str, Any]:
    harness = NativeBuilderHarness(
        runtime=runtime,
        llm_client=llm,
        tool_executor=ToolExecutor(registry=runtime.tool_registry),
        tool_registry=runtime.tool_registry,
        structured_tool_messages=runtime.config.agentic_loop.structured_tool_messages,
    )
    spec = BuildSpec(
        title="Fixture build", description="Inspect the fixture and report.",
        target_files=["src/widget.py"] if paths else [],
        reference_files=["README.md"] if paths else [],
        test_files=["tests/test_widget.py"] if paths else [],
        constraints=["Keep source output unchanged."], ad_number=1200,
    )
    return await harness.run_build(spec, cwd, agent_id=_AGENT)


async def _work_item(
    runtime: SimpleNamespace, llm: _FakeLLM, tool: str, **kwargs: Any,
) -> Any:
    await runtime.tool_permission_store.issue_grant(_AGENT, tool, ToolPermission.READ)
    result = await WorkItemAgenticExecutor(llm_client=llm).run(
        agent_id=_AGENT, instructions="FIXTURE GOVERNANCE",
        task_text="Read the explicitly named source file.",
        runtime=runtime, department="engineering", rank="lieutenant",
        **kwargs,
    )
    assert not result.denied_tools
    assert result.stopped_reason == "complete"
    assert len(runtime.attachment_store.blobs) == 1
    return result


def _normalized(value: Any, fixture: PurePath) -> str:
    # The immutable oracle was captured on Windows. Canonicalize only these
    # owned fixture locations, including paths inside JSON-encoded strings.
    locations = (
        (fixture / "project" / "src" / "widget.py", "<FIXTURE>\\project\\src\\widget.py"),
        (fixture / "project", "<FIXTURE>\\project"),
        (fixture / "missing", "<FIXTURE>\\missing"),
        (fixture, "<FIXTURE>"),
        (_ROOT, "<SOURCE_REPOSITORY>"),
    )

    def token_offsets(token: str, decoded: str) -> list[int]:
        offsets = [1]
        position = 1
        while position < len(token) - 1:
            if token[position] != "\\":
                position += 1
            elif token[position + 1] != "u":
                position += 2
            else:
                codepoint = int(token[position + 2:position + 6], 16)
                position += 6
                if (
                    0xD800 <= codepoint <= 0xDBFF and token.startswith("\\u", position)
                    and 0xDC00 <= int(token[position + 2:position + 6], 16) <= 0xDFFF
                ):
                    position += 6
            offsets.append(position)
        assert len(offsets) == len(decoded) + 1
        return offsets

    def path_edits(item: str) -> list[tuple[int, int, str]]:
        changes: list[tuple[int, int, str]] = []
        if item.lstrip().startswith(("{", "[")):
            try:
                encoded = json.loads(item)
            except json.JSONDecodeError:
                encoded = None
            if isinstance(encoded, (dict, list)):
                for match in _JSON_STRING.finditer(item):
                    text = json.loads(match.group())
                    nested = path_edits(text)
                    if not nested:
                        continue
                    offsets = token_offsets(match.group(), text)
                    for start, end, replacement in nested:
                        changes.append((
                            match.start() + offsets[start],
                            match.start() + offsets[end],
                            json.dumps(replacement, ensure_ascii=False)[1:-1],
                        ))
                return changes
        for path, label in locations:
            for spelling in (str(path), path.as_posix()):
                for match in re.finditer(re.escape(spelling), item):
                    if not any(
                        match.start() < end and match.end() > start
                        for start, end, _ in changes
                    ):
                        changes.append((match.start(), match.end(), label))
        return sorted(changes)

    def normalize_string(item: str) -> str:
        parts: list[str] = []
        previous = 0
        for start, end, replacement in path_edits(item):
            parts.extend((item[previous:start], replacement))
            previous = end
        parts.append(item[previous:])
        return "".join(parts)

    def normalize(item: Any) -> Any:
        if isinstance(item, str):
            return normalize_string(item)
        if isinstance(item, dict):
            return {key: normalize(part) for key, part in item.items()}
        if isinstance(item, list):
            return [normalize(part) for part in item]
        return item

    return json.dumps(normalize(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _fingerprint(value: Any, fixture: Path) -> dict[str, Any]:
    raw = _normalized(value, fixture).encode("utf-8")
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


async def _capture_no_instructions(
    fixture: Path, monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    import probos.types as types_module

    monkeypatch.setattr(
        types_module, "uuid", SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="fixture-request")),
    )
    repo, source = _repo(fixture)
    cases: dict[str, Any] = {}
    for structured in (False, True):
        mode = "structured" if structured else "legacy"
        for location, cwd in (
            ("repository", str(repo)),
            ("missing", str(fixture / "missing")),
            ("unscoped", ""),
            ("installed", str(_ROOT)),
        ):
            runtime = _runtime(fixture, structured=structured)
            responses = [_read(source), _text()] if location == "repository" else [_text()]
            llm = _FakeLLM(responses)
            result = await _native(runtime, llm, cwd, paths=location == "repository")
            assert result["metadata"]["stopped_reason"] == "complete"
            assert len(llm.requests) == (2 if location == "repository" else 1)
            assert not llm.responses
            if location == "repository":
                assert "alpha" in _normalized(asdict(llm.requests[1]), fixture)
            cases[f"native/{location}/{mode}"] = {
                "requests": [_fingerprint(asdict(req), fixture) for req in llm.requests],
                "result": _fingerprint(result, fixture),
            }
        for tool in ("read_file", "codebase_read_source"):
            runtime = _runtime(fixture, structured=structured)
            llm = _FakeLLM([_read(source, tool), _text()])
            await _work_item(runtime, llm, tool)
            assert len(llm.requests) == 2 and not llm.responses
            assert tool in {d["function"]["name"] for d in llm.requests[0].tools or []}
            assert "alpha" in _normalized(asdict(llm.requests[1]), fixture)
            cases[f"work_item/{tool}/{mode}"] = {
                "requests": [_fingerprint(asdict(req), fixture) for req in llm.requests],
                "trace": _fingerprint(runtime.attachment_store.blobs[0].decode("utf-8"), fixture),
            }
    return {
        "base": _BASE,
        "normalization": "fixture and source-repository paths only",
        "tool_result_fields": [f.name for f in fields(ToolResult)],
        "tool_call_result_fields": [f.name for f in fields(ToolCallResult)],
        "cases": cases,
    }


@pytest.mark.asyncio
async def test_no_instructions_actual_requests_match_pinned_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = await _capture_no_instructions(tmp_path, monkeypatch)
    assert observed == json.loads(_GOLDEN.read_text(encoding="utf-8"))


@pytest.mark.parametrize("encoding", ["plain", "json", "nested_json"])
def test_golden_fixture_path_normalization_is_portable_without_weakening_data(
    encoding: str,
) -> None:
    windows = PureWindowsPath("C:\\owned-fixture")
    posix = PurePosixPath("/tmp/owned-fixture")

    def value(root: PurePath, identifier: str = "unchanged") -> Any:
        payload = {"path": str(root / "project" / "src" / "widget.py"), "identifier": identifier}
        if encoding == "json":
            return json.dumps(payload, indent=2)
        if encoding == "nested_json":
            return {"function": {"arguments": json.dumps(payload)}, "count": 39}
        return payload

    canonical = _normalized(value(windows), windows)
    assert _normalized(value(posix), posix) == canonical
    assert _normalized(value(posix, "changed"), posix) != canonical
    assert "unchanged" in canonical


@pytest.mark.parametrize("marker", ["\u00e9", "\U0001f680"])
@pytest.mark.parametrize("position", ["before", "after"])
@pytest.mark.parametrize("nested", [False, True])
def test_golden_normalization_preserves_nonpath_escape_bytes_inside_path_tokens(
    marker: str, position: str, nested: bool,
) -> None:
    fixture = PurePosixPath("/tmp/owned-fixture")
    path = str(fixture / "project" / "src" / "widget.py")
    text = f"{marker} {path}" if position == "before" else f"{path} {marker}"
    literal = json.dumps({"value": text}, ensure_ascii=False, indent=2)
    escaped = json.dumps({"value": text}, ensure_ascii=True, indent=2)
    assert literal != escaped and json.loads(literal) == json.loads(escaped)
    if nested:
        literal = json.dumps({"arguments": literal}, ensure_ascii=False)
        escaped = json.dumps({"arguments": escaped}, ensure_ascii=False)
    left = _normalized(literal, fixture)
    right = _normalized(escaped, fixture)
    assert left != right
    assert "<FIXTURE>" in left and "<FIXTURE>" in right


def _guidance(root: Path, path: str, text: str) -> Path:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def _instruction_frames(prompt: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in prompt.splitlines() if line.startswith('{"source":')]


def _transcript(request: LLMRequest) -> str:
    return request.prompt + json.dumps(request.messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_native_build_guidance_reaches_first_and_next_actual_requests(
    tmp_path: Path, structured: bool,
) -> None:
    repo, source = _repo(tmp_path)
    runtime = _runtime(tmp_path, structured=structured)
    _guidance(runtime.data_dir, "repository-instructions/AGENTS.md", "GLOBAL-MARKER")
    _guidance(repo, "AGENTS.md", "SUPPRESSED-MARKER")
    _guidance(repo, "AGENTS.override.md", "ROOT-MARKER")
    _guidance(repo, "src/AGENTS.md", "NEAREST-MARKER")
    llm = _FakeLLM([_read(source), _text()])
    result = await _native(runtime, llm, str(repo))
    assert result["metadata"]["stopped_reason"] == "complete"
    assert len(llm.requests) == 2 and not llm.responses
    for request in llm.requests:
        assert (request.messages is not None) is structured
        assert request.system_prompt.count("<repository-instructions>") == 1
        assert [frame["content"] for frame in _instruction_frames(request.system_prompt)] == [
            "GLOBAL-MARKER", "ROOT-MARKER", "NEAREST-MARKER",
        ]
        assert "SUPPRESSED-MARKER" not in request.system_prompt
        assert "MARKER" not in _transcript(request)
    assert llm.requests[0].system_prompt == llm.requests[1].system_prompt
    assert "alpha" in _transcript(llm.requests[1])
    assert "MARKER" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("tool", ["read_file", "codebase_read_source"])
@pytest.mark.parametrize("root_kind", ["override", "fallback"])
async def test_registered_file_adapter_work_item_next_parent_request_and_durable_bytes(
    tmp_path: Path, structured: bool, tool: str, root_kind: str,
) -> None:
    repo, source = _repo(tmp_path)
    runtime = _runtime(tmp_path, structured=structured)
    _guidance(runtime.data_dir, "repository-instructions/AGENTS.override.md", "GLOBAL-MARKER")
    root_path = "AGENTS.override.md" if root_kind == "override" else ".github/copilot-instructions.md"
    _guidance(repo, root_path, "ROOT-MARKER")
    _guidance(repo, "src/AGENTS.md", "NEAREST-MARKER")
    llm = _FakeLLM([_read(source, tool), _text()])
    await _work_item(runtime, llm, tool)
    assert len(llm.requests) == 2 and not llm.responses
    assert llm.requests[0].system_prompt == "FIXTURE GOVERNANCE"
    assert tool in {item["function"]["name"] for item in llm.requests[0].tools or []}
    second = llm.requests[1]
    assert (second.messages is not None) is structured
    frames = _instruction_frames(second.system_prompt)
    assert [frame["content"] for frame in frames] == [
        "GLOBAL-MARKER", "ROOT-MARKER", "NEAREST-MARKER",
    ]
    assert frames[1]["scope"] == str(repo)
    assert frames[2]["scope"] == str(source.parent)
    assert second.system_prompt.count("<repository-instructions>") == 1
    assert "MARKER" not in _transcript(second)
    assert "alpha" in _transcript(second)
    golden = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    key = f"work_item/{tool}/{'structured' if structured else 'legacy'}"
    assert _fingerprint(runtime.attachment_store.blobs[0].decode(), tmp_path) == golden["cases"][key]["trace"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["read_file", "codebase_read_source"])
async def test_reader_extensions_preserve_slicing_output_metadata_and_errors(
    tmp_path: Path, tool: str,
) -> None:
    repo, source = _repo(tmp_path)
    runtime = _runtime(tmp_path)
    _guidance(repo, "AGENTS.md", "NOT-SOURCE-OUTPUT")
    reader = runtime.tool_registry.get(tool).tool
    params = (
        {"path": str(source), "offset": 1, "limit": 1}
        if tool == "read_file" else
        {"file_path": str(source), "start_line": 2, "end_line": 2}
    )
    result = await reader.invoke(params)
    assert isinstance(result, InstructionToolResult)
    assert result.output == "beta" and result.metadata == {} and result.error is None
    assert "NOT-SOURCE-OUTPUT" not in repr(result)
    adapted = ToolCallResult.from_tool_result("call", result, 12.5)
    assert isinstance(adapted, InstructionToolCallResult)
    assert adapted.output == "beta" and adapted.duration_ms == 12.5
    assert adapted.repository_instructions is result.repository_instructions
    with pytest.raises(FrozenInstanceError):
        adapted.repository_instructions = InstructionObservation()
    assert (await reader.invoke({})).error is not None
    key = "path" if tool == "read_file" else "file_path"
    missing = await reader.invoke({key: str(repo / "absent.py")})
    assert type(missing) is ToolResult and missing.error.startswith("File not found:")
    failed = InstructionToolResult(error="failed", repository_instructions=result.repository_instructions)
    assert type(ToolCallResult.from_tool_result("call", failed, 0)) is ToolCallResult


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["read_file", "codebase_read_source"])
async def test_denied_reader_never_discovers_or_exempts_global_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str,
) -> None:
    from probos.cognitive.swe_harness import tools as tools_module

    runtime = _runtime(tmp_path)
    forbidden = _guidance(runtime.data_dir, "repository-instructions/AGENTS.md", "PRIVATE-MARKER")

    def unexpected(*args: Any, **kwargs: Any) -> None:
        pytest.fail("denied source read attempted repository discovery")

    monkeypatch.setattr(tools_module, "discover_repository_instructions", unexpected)
    reader = runtime.tool_registry.get(tool).tool
    key = "path" if tool == "read_file" else "file_path"
    result = await reader.invoke({key: str(forbidden)})
    assert type(result) is ToolResult and result.error is not None
    assert result.output is None and result.metadata == {}
    assert "PRIVATE-MARKER" not in result.error


@pytest.mark.asyncio
async def test_instruction_extensions_and_loop_reject_untyped_observations(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        InstructionToolResult(repository_instructions={})
    with pytest.raises(TypeError):
        InstructionToolCallResult(id="call", repository_instructions={})
    runtime = _runtime(tmp_path)
    loop = AgenticLoop(llm_client=_FakeLLM([]), tool_executor=ToolExecutor(registry=runtime.tool_registry))
    with pytest.raises(TypeError):
        await loop.run(system_prompt="base", user_message="task", tools=[], context={}, repository_instructions={})
    with pytest.raises(ValueError, match="agentic_context_invalid"):
        await WorkItemAgenticExecutor(llm_client=_FakeLLM([])).run(
            agent_id=_AGENT, instructions="base", task_text="task", runtime=runtime,
            extra_context={"cwd": str(tmp_path)},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_work_item_compaction_and_accounting_use_same_effective_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, structured: bool,
) -> None:
    from probos.cognitive.swe_harness import agentic_loop as loop_module

    repo, source = _repo(tmp_path)
    runtime = _runtime(tmp_path, structured=structured)
    _guidance(repo, "AGENTS.md", "COMPACTION-MARKER")
    before_compaction: list[list[dict[str, Any]]] = []
    outbound_accounting: list[list[dict[str, Any]]] = []
    charges: list[int] = []

    class _FakeCompactor:
        async def compact(self, messages: list[dict[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
            before_compaction.append(copy.deepcopy(messages))
            return [copy.deepcopy(message) for message in messages if message["role"] != "system"]

    original = loop_module._estimate_call_tokens

    def estimate(messages: list[dict[str, Any]], response: LLMResponse) -> int:
        outbound_accounting.append(copy.deepcopy(messages))
        charge = original(messages, response)
        charges.append(charge)
        return charge

    monkeypatch.setattr(loop_module, "_estimate_call_tokens", estimate)
    first, second = _read(source), _text()
    first.tokens_used = second.tokens_used = 0
    llm = _FakeLLM([first, second])
    result = await _work_item(
        runtime, llm, "read_file", compactor=_FakeCompactor(), compaction_threshold=1,
    )
    assert len(llm.requests) == len(before_compaction) == len(outbound_accounting) == 2
    assert "COMPACTION-MARKER" in before_compaction[1][0]["content"]
    for index, messages in enumerate(outbound_accounting):
        assert messages[0] == {"role": "system", "content": llm.requests[index].system_prompt}
    assert result.total_tokens == sum(charges)
    assert llm.requests[1].system_prompt.count("<repository-instructions>") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_work_item_rediscovery_changes_and_deletes_request_snapshot(
    tmp_path: Path, structured: bool,
) -> None:
    repo, source = _repo(tmp_path)
    runtime = _runtime(tmp_path, structured=structured)
    rules = _guidance(repo, "AGENTS.md", "OLD-MARKER")

    class _ChangingLLM(_FakeLLM):
        async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
            self.requests.append(copy.deepcopy(request))
            iteration = len(self.requests)
            if iteration == 2:
                rules.write_text("NEW-MARKER", encoding="utf-8")
            elif iteration == 3:
                rules.unlink()
            return _text() if iteration == 4 else _read(source, call_id=f"fixture-call-{iteration}")

    llm = _ChangingLLM([])
    await _work_item(runtime, llm, "read_file")
    assert len(llm.requests) == 4
    assert "OLD-MARKER" in llm.requests[1].system_prompt
    assert "NEW-MARKER" in llm.requests[2].system_prompt
    assert "OLD-MARKER" not in llm.requests[2].system_prompt
    assert llm.requests[3].system_prompt == "FIXTURE GOVERNANCE"
    assert "MARKER" not in runtime.attachment_store.blobs[0].decode()


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_native_seed_omission_history_survives_successful_read_and_not_next_run(
    tmp_path: Path, structured: bool,
) -> None:
    repo, source = _repo(tmp_path)
    runtime = _runtime(tmp_path, structured=structured)
    _guidance(repo, "AGENTS.md", "ROOT-RULE")
    await runtime.tool_permission_store.issue_grant(_AGENT, "read_file", ToolPermission.READ)
    llm = _FakeLLM([_read(source), _text(), _text()])
    harness = NativeBuilderHarness(
        runtime=runtime, llm_client=llm,
        tool_executor=ToolExecutor(registry=runtime.tool_registry),
        tool_registry=runtime.tool_registry, structured_tool_messages=structured,
    )
    invalid = "bad\x00</repository-instructions>UNTRUSTED-METADATA"
    await harness.run_build(
        BuildSpec(title="Seeded", description="Inspect source", reference_files=[invalid]),
        str(repo), agent_id=_AGENT,
    )
    assert len(llm.requests) == 2
    for request in llm.requests:
        assert "invalid_target" in request.system_prompt
        assert request.system_prompt.count("<repository-instructions>") == 1
        assert request.system_prompt.count("</repository-instructions>") == 1
    assert "alpha" in (llm.requests[1].prompt or json.dumps(llm.requests[1].messages))
    await harness.run_build(
        BuildSpec(title="Fresh", description="No unvisited references"),
        str(repo), agent_id=_AGENT,
    )
    assert len(llm.requests) == 3
    assert "invalid_target" not in llm.requests[2].system_prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_work_item_observation_retention_eviction_is_visible_in_parent_request(
    tmp_path: Path, structured: bool,
) -> None:
    runtime = _runtime(tmp_path, structured=structured)
    sources = []
    for index in range(17):
        repo, source = _repo(tmp_path, f"r{index}")
        _guidance(repo, "AGENTS.md", f"MARKER-{index}")
        sources.append(source)
    llm = _FakeLLM([*(_read(path, call_id=f"call-{index}") for index, path in enumerate(sources)), _text()])
    await _work_item(runtime, llm, "read_file", max_iterations=20)
    assert len(llm.requests) == 18 and not llm.responses
    last = llm.requests[-1].system_prompt
    assert last.count("<repository-instructions>") == 1
    assert "evicted targets: 1" in last
    assert {frame["content"] for frame in _instruction_frames(last)} == {f"MARKER-{i}" for i in range(1, 17)}
    assert len(last.removeprefix("FIXTURE GOVERNANCE").encode()) <= 32768


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_real_loop_keeps_outer_exclusion_after_nested_target_eviction(
    tmp_path: Path, structured: bool,
) -> None:
    outer, source = _repo(tmp_path, "outer")
    inner, inner_source = _repo(outer, "inner")
    source = outer / "root.py"
    source.write_text("ROOT-SOURCE", encoding="utf-8")
    _guidance(outer, "AGENTS.md", "OUTER-RULE")
    runtime = _runtime(tmp_path, structured=structured)
    await runtime.tool_permission_store.issue_grant(_AGENT, "read_file", ToolPermission.READ)
    other_sources = [_repo(tmp_path, f"other-{index}")[1] for index in range(15)]
    llm = _FakeLLM([
        _read(source, call_id="refresh-outer"),
        *(_read(path, call_id=f"other-{index}") for index, path in enumerate(other_sources)),
        _text(),
    ])
    harness = NativeBuilderHarness(
        runtime=runtime, llm_client=llm,
        tool_executor=ToolExecutor(registry=runtime.tool_registry),
        tool_registry=runtime.tool_registry, structured_tool_messages=structured,
    )
    result = await harness.run_build(
        BuildSpec(title="Mixed repository build", description="Inspect source", target_files=[str(inner_source)]),
        str(outer), agent_id=_AGENT,
    )
    assert result["metadata"]["tools_used"] == ["read_file"] * 16
    assert len(llm.requests) == 17 and not llm.responses
    first = next(frame for frame in _instruction_frames(llm.requests[0].system_prompt) if frame["content"] == "OUTER-RULE")
    last = next(frame for frame in _instruction_frames(llm.requests[-1].system_prompt) if frame["content"] == "OUTER-RULE")
    assert first["excluded_repositories"] == last["excluded_repositories"] == [str(inner)]
    assert "evicted targets: 1" in llm.requests[-1].system_prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("nested", [False, True])
async def test_shared_loop_nested_and_concurrent_runs_keep_observations_local(
    tmp_path: Path, nested: bool,
) -> None:
    runtime = _runtime(tmp_path, structured=True)
    files: dict[str, Path] = {}
    for label in ("A", "B"):
        repo, source = _repo(tmp_path, label)
        _guidance(repo, "AGENTS.md", f"ONLY-{label}")
        files[label] = source
    requests: dict[str, list[LLMRequest]] = {"A": [], "B": []}
    loop: AgenticLoop

    async def run(label: str) -> Any:
        return await loop.run(
            system_prompt="BASE", user_message=label, tools=[],
            context={"agent_id": _AGENT, "rank": "lieutenant"},
        )

    class _InterleavedLLM:
        async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
            label = request.messages[0]["content"]
            requests[label].append(copy.deepcopy(request))
            if len(requests[label]) == 1:
                await asyncio.sleep(0)
                return _read(files[label])
            if nested and label == "A":
                assert (await run("B")).stopped_reason == "complete"
            return _text()

    loop = AgenticLoop(
        llm_client=_InterleavedLLM(), tool_executor=ToolExecutor(registry=runtime.tool_registry),
        structured_tool_messages=True,
    )
    if nested:
        assert (await run("A")).stopped_reason == "complete"
    else:
        results = await asyncio.gather(run("A"), run("B"))
        assert all(result.stopped_reason == "complete" for result in results)
    for label in ("A", "B"):
        assert len(requests[label]) == 2
        assert requests[label][0].system_prompt == "BASE"
        assert [part["content"] for part in _instruction_frames(requests[label][1].system_prompt)] == [f"ONLY-{label}"]


@pytest.mark.asyncio
async def test_cancelled_loop_drops_guidance_before_next_run(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, structured=True)
    repo, source = _repo(tmp_path)
    _guidance(repo, "AGENTS.md", "CANCELLED-MARKER")
    waiting = asyncio.Event()
    never = asyncio.Event()

    class _CancellationLLM(_FakeLLM):
        async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
            self.requests.append(copy.deepcopy(request))
            label = request.messages[0]["content"]
            if label == "cancel" and len(self.requests) == 1:
                return _read(source)
            if label == "cancel":
                waiting.set()
                await never.wait()
            return _text()

    llm = _CancellationLLM([])
    loop = AgenticLoop(
        llm_client=llm, tool_executor=ToolExecutor(registry=runtime.tool_registry),
        structured_tool_messages=True,
    )
    task = asyncio.create_task(loop.run(
        system_prompt="BASE", user_message="cancel", tools=[],
        context={"agent_id": _AGENT, "rank": "lieutenant"},
    ))
    try:
        await waiting.wait()
        assert "CANCELLED-MARKER" in llm.requests[-1].system_prompt
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    await loop.run(system_prompt="BASE", user_message="fresh", tools=[], context={})
    assert llm.requests[-1].system_prompt == "BASE"


@pytest.mark.asyncio
async def test_fake_sdk_session_receives_bounded_scoped_guidance_without_permission_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.cognitive import copilot_adapter as sdk

    repo, source = _repo(tmp_path)
    runtime = _runtime(tmp_path)
    _guidance(runtime.data_dir, "repository-instructions/AGENTS.md", "GLOBAL-MARKER")
    root_rules = _guidance(repo, "AGENTS.md", "ROOT-MARKER")
    nearest = _guidance(repo, "src/AGENTS.override.md", "NEAREST-MARKER")
    approved = object()
    configs: list[dict[str, Any]] = []
    lifecycle: list[str] = []

    class _FakeSession:
        async def send_and_wait(self, prompt: dict[str, str], *, timeout: float) -> None:
            assert "Fixture SDK" in prompt["prompt"]

        async def get_messages(self) -> list[Any]:
            return [SimpleNamespace(type="assistant", data=SimpleNamespace(content="done"))]

        async def disconnect(self) -> None:
            lifecycle.append("disconnect")

    class _FakeClient:
        def __init__(self, options: dict[str, Any]) -> None:
            assert options["cwd"] == str(repo)
            assert options["use_logged_in_user"] is True

        async def start(self) -> None:
            lifecycle.append("start")

        async def create_session(self, config: dict[str, Any]) -> _FakeSession:
            configs.append(config)
            return _FakeSession()

        async def stop(self) -> None:
            lifecycle.append("stop")

    monkeypatch.setattr(sdk, "_SDK_AVAILABLE", True)
    monkeypatch.setattr(sdk, "CopilotClient", _FakeClient, raising=False)
    monkeypatch.setattr(sdk, "PermissionHandler", SimpleNamespace(approve_all=approved), raising=False)
    monkeypatch.setattr(sdk, "SessionEventType", SimpleNamespace(ASSISTANT_MESSAGE="assistant"), raising=False)
    monkeypatch.setattr(sdk, "Tool", lambda **kwargs: SimpleNamespace(**kwargs), raising=False)
    adapter = sdk.CopilotBuilderAdapter(cwd=str(repo), runtime=runtime)
    base_message = adapter._compose_system_message()
    files = {str(path.relative_to(repo)).replace("\\", "/"): path.read_text(encoding="utf-8") for path in (source, root_rules, nearest)}
    await adapter.start()
    try:
        result = await adapter.execute(BuildSpec(
            title="Fixture SDK", description="No file changes.", target_files=["src/widget.py"],
        ), files)
    finally:
        await adapter.stop()
    assert lifecycle == ["start", "disconnect", "stop"]
    assert len(configs) == 1
    config = configs[0]
    assert config["working_directory"] == str(repo)
    assert config["on_permission_request"] is approved
    assert config["system_message"]["mode"] == base_message["mode"]
    prompt = config["system_message"]["content"]
    assert prompt.startswith(base_message["content"])
    assert len(prompt.removeprefix(base_message["content"]).encode()) <= 32768
    assert [frame["content"] for frame in _instruction_frames(prompt)] == [
        "GLOBAL-MARKER", "ROOT-MARKER", "NEAREST-MARKER",
    ]
    assert result.raw_output == "done"
    assert result.file_blocks == [] and "MARKER" not in repr(result)
