"""AD-1068: UseSkillTool — load a cognitive skill into the conversational loop.

Substrate-honest: a REAL ``CognitiveSkillCatalog`` scans a REAL fixture skill on
disk, and the loop integration runs the skill's bundled script through the REAL
``SubprocessSandbox`` (AD-993) so its output lands as a downloadable artifact —
proving the executable-skill bridge end to end (catalog → use_skill → run_python
→ artifact).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from probos.artifacts import ArtifactStore
from probos.config import ExecutionConfig
from probos.cognitive.skill_catalog import CognitiveSkillCatalog
from probos.tools.use_skill_tool import UseSkillTool


# ── fixtures ──────────────────────────────────────────────────────────────
def _write_skill(
    skills_root: Path,
    name: str,
    *,
    department: str | None = None,
    min_rank: str | None = None,
    writes: str = "out.txt",
) -> Path:
    """Create a real fixture skill folder: SKILL.md + scripts/make.py."""
    d = skills_root / name
    (d / "scripts").mkdir(parents=True, exist_ok=True)
    meta_lines = ""
    if department is not None or min_rank is not None:
        meta_lines = "metadata:\n"
        if department is not None:
            meta_lines += f"  probos-department: {department}\n"
        if min_rank is not None:
            meta_lines += f"  probos-min-rank: {min_rank}\n"
    (d / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        "description: A test skill that creates a file.\n"
        f"{meta_lines}"
        "---\n\n"
        f"# {name}\n\nRun scripts/make.py to produce the deliverable.\n",
        encoding="utf-8",
    )
    (d / "scripts" / "make.py").write_text(
        f"with open({writes!r}, 'w', encoding='utf-8') as f:\n"
        "    f.write('skill output')\n"
        "print('made it')\n",
        encoding="utf-8",
    )
    return d


async def _catalog(skills_root: Path) -> CognitiveSkillCatalog:
    cat = CognitiveSkillCatalog(skills_dir=skills_root)
    await cat.start()  # db_path=None ⇒ in-memory scan only
    return cat


class _FakeAttachmentStore:
    """Protocol-faithful in-memory AttachmentStore (AD-720 write signature)."""

    def __init__(self) -> None:
        self.blobs: dict[str, tuple[bytes, str, str]] = {}

    async def write(self, content_hash, blob, mime, *, origin="chat_attachment"):
        self.blobs[content_hash] = (blob, mime, origin)
        return Path(f"/fake/{content_hash}")


# ── unit: UseSkillTool ────────────────────────────────────────────────────
async def test_no_catalog_returns_error() -> None:
    tool = UseSkillTool(runtime=SimpleNamespace(cognitive_skill_catalog=None))
    result = await tool.invoke({"name": "docx"}, {"agent_id": "ezri"})
    assert result.error is not None
    assert "catalog" in result.error.lower()


async def test_found_returns_body_skill_dir_and_manifest(tmp_path) -> None:
    skills = tmp_path / "skills"
    _write_skill(skills, "docx-fixture")
    cat = await _catalog(skills)
    tool = UseSkillTool(runtime=SimpleNamespace(cognitive_skill_catalog=cat))

    result = await tool.invoke(
        {"name": "docx-fixture"}, {"agent_id": "ezri", "department": "", "rank": ""},
    )

    assert result.error is None
    out = result.output
    assert out["found"] is True
    assert out["name"] == "docx-fixture"
    # The SKILL.md body (below the frontmatter) is returned for the loop context.
    assert "Run scripts/make.py" in out["instructions"]
    # skill_dir is absolute + points at the fixture folder.
    assert Path(out["skill_dir"]).resolve() == (skills / "docx-fixture").resolve()
    # The bundled script is in the manifest (SKILL.md itself is excluded).
    paths = {f["path"] for f in out["files"]}
    assert "scripts/make.py" in paths
    assert "SKILL.md" not in paths
    # Each manifest entry carries an absolute path the loop can run by.
    make = next(f for f in out["files"] if f["path"] == "scripts/make.py")
    assert Path(make["abs"]).is_file()


async def test_unknown_name_lists_available(tmp_path) -> None:
    skills = tmp_path / "skills"
    _write_skill(skills, "docx-fixture")
    cat = await _catalog(skills)
    tool = UseSkillTool(runtime=SimpleNamespace(cognitive_skill_catalog=cat))

    result = await tool.invoke({"name": "nope"}, {"agent_id": "ezri"})

    # Honest-degrade: not an error — a discovery result with the available list.
    assert result.error is None
    assert result.output["found"] is False
    assert "docx-fixture" in result.output["available"]


async def test_empty_name_lists_available(tmp_path) -> None:
    skills = tmp_path / "skills"
    _write_skill(skills, "docx-fixture")
    cat = await _catalog(skills)
    tool = UseSkillTool(runtime=SimpleNamespace(cognitive_skill_catalog=cat))

    result = await tool.invoke({"name": "  "}, {"agent_id": "ezri"})

    assert result.error is None
    assert result.output["found"] is False
    assert "docx-fixture" in result.output["available"]


async def test_department_visibility_excludes_out_of_dept_skill(tmp_path) -> None:
    skills = tmp_path / "skills"
    _write_skill(skills, "ship-wide")              # department defaults to "*"
    _write_skill(skills, "lab-skill", department="science")
    cat = await _catalog(skills)
    tool = UseSkillTool(runtime=SimpleNamespace(cognitive_skill_catalog=cat))

    eng_ctx = {"agent_id": "ezri", "department": "engineering", "rank": "ensign"}
    # The ship-wide ("*") skill is visible to engineering.
    ship = await tool.invoke({"name": "ship-wide"}, eng_ctx)
    assert ship.output["found"] is True
    # The science-only skill is NOT visible to an engineering agent.
    lab = await tool.invoke({"name": "lab-skill"}, eng_ctx)
    assert lab.output["found"] is False
    assert "lab-skill" not in lab.output["available"]


def test_tool_protocol_shape() -> None:
    tool = UseSkillTool(runtime=SimpleNamespace())
    assert tool.tool_id == "use_skill"
    assert isinstance(tool.input_schema, dict)
    assert "name" in tool.input_schema["properties"]
    assert "skill" in tool.description.lower()


# ── loop integration ──────────────────────────────────────────────────────
class _FakeLLMResponse:
    def __init__(self, content_blocks, content="", tokens=1):
        self.content_blocks = content_blocks
        self.content = content
        self.tokens_used = tokens


class _ScriptedLLM:
    def __init__(self, responses):
        self._responses = list(responses)
        self.last_tools = None

    async def complete(self, req, **_kwargs):
        self.last_tools = list(getattr(req, "tools", None) or [])
        if self._responses:
            return self._responses.pop(0)
        return _FakeLLMResponse(content_blocks=[], content="done")


def _tool_use(tool_id, args):
    from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolUseBlock

    return _FakeLLMResponse(
        content_blocks=[ToolUseBlock(tool_call=ToolCallRequest(name=tool_id, arguments=args))],
        content="",
        tokens=1,
    )


def _text(text):
    return _FakeLLMResponse(content_blocks=[], content=text, tokens=1)


def _tool_names(last_tools):
    return [
        (t.get("function", {}) or {}).get("name") or t.get("name")
        for t in (last_tools or [])
    ]


def _loop_runtime(tmp_path, *, enabled: bool, catalog):
    from probos.tools.permissions import ToolPermissionStore
    from probos.tools.registry import ToolRegistry

    return SimpleNamespace(
        config=SimpleNamespace(
            execution=ExecutionConfig(
                enabled=enabled, scratch_dir=str(tmp_path / "scratch"),
            ),
            mcp=None,
        ),
        tool_registry=ToolRegistry(),
        tool_permission_store=ToolPermissionStore(),
        intent_bus=None,
        intent_grant_store=None,
        mcp_workbench=None,
        attachment_store=_FakeAttachmentStore(),
        artifact_store=ArtifactStore(tmp_path / "artifacts.db"),
        cognitive_skill_catalog=catalog,
        emit_event=None,
    )


async def test_loop_offers_use_skill_when_catalog_present(tmp_path) -> None:
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor

    skills = tmp_path / "skills"
    _write_skill(skills, "docx-fixture")
    cat = await _catalog(skills)
    runtime = _loop_runtime(tmp_path, enabled=True, catalog=cat)
    llm = _ScriptedLLM([_text("hello, Captain")])
    executor = WorkItemAgenticExecutor(llm_client=llm)

    outcome = await executor.run(
        agent_id="ezri",
        instructions="You are Ezri.",
        task_text="hi",
        runtime=runtime,
        thread_id="t",
        max_iterations=3,
    )

    assert outcome.final_text == "hello, Captain"
    assert "use_skill" in _tool_names(llm.last_tools)
    assert runtime.tool_registry.get("use_skill") is not None


async def test_loop_omits_use_skill_when_no_catalog(tmp_path) -> None:
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor

    runtime = _loop_runtime(tmp_path, enabled=True, catalog=None)
    llm = _ScriptedLLM([_text("hi")])
    executor = WorkItemAgenticExecutor(llm_client=llm)

    outcome = await executor.run(
        agent_id="ezri", instructions="You are Ezri.", task_text="hi",
        runtime=runtime, thread_id="t", max_iterations=2,
    )

    assert outcome.final_text == "hi"
    assert "use_skill" not in _tool_names(llm.last_tools)
    assert runtime.tool_registry.get("use_skill") is None


async def test_loop_use_skill_then_run_python_produces_artifact(tmp_path) -> None:
    """THE AD-1068 GOAL: an agent in the loop loads a skill, runs its bundled
    script via run_python, and the script's output lands as a downloadable
    artifact on the chat thread (executable-skill parity)."""
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor

    skills = tmp_path / "skills"
    _write_skill(skills, "docx-fixture", writes="deliverable.txt")
    cat = await _catalog(skills)
    runtime = _loop_runtime(tmp_path, enabled=True, catalog=cat)

    make_abs = str((skills / "docx-fixture" / "scripts" / "make.py").resolve())
    run_code = (
        "import subprocess, sys\n"
        f"subprocess.run([sys.executable, {make_abs!r}], check=True)\n"
        "print('ran the skill script')\n"
    )
    llm = _ScriptedLLM([
        _tool_use("use_skill", {"name": "docx-fixture"}),
        _tool_use("run_python", {"code": run_code}),
        _text("Done — deliverable.txt is ready, Captain."),
    ])
    executor = WorkItemAgenticExecutor(llm_client=llm)

    outcome = await executor.run(
        agent_id="ezri",
        instructions="You are Ezri.",
        task_text="use the docx skill to make my file",
        runtime=runtime,
        department="counseling",
        rank="lieutenant",
        thread_id="thread-skill",
        max_iterations=5,
    )

    assert outcome.final_text == "Done — deliverable.txt is ready, Captain."
    # Both the skills bridge and the executor were offered to the model.
    offered = _tool_names(llm.last_tools)
    assert "use_skill" in offered
    assert "run_python" in offered
    # The skill's script produced a real artifact on the thread.
    arts = runtime.artifact_store.list_thread_latest("thread-skill")
    assert len(arts) == 1
    assert arts[0].name == "deliverable.txt"
    assert arts[0].created_by == "ezri"
    blob, _mime, origin = runtime.attachment_store.blobs[arts[0].content_hash]
    assert blob == b"skill output"
    assert origin == "agent_artifact"
