# AD-1068 — Executable-skill runtime (`use_skill` tool)

**Issue:** seangalliher/ProbOS#1007 · **Epic:** #1006 · **Spec:** `prompts/ad-1065-conversational-tools-skills-epic.md` §AD-1068

**Current highest minted top-level AD: AD-1066** (AD-1055–1066 this session, uncommitted; AD-1067 folded into AD-1066). This is **AD-1068** — the next sequential top-level, reserved by the epic for the skills bridge.

---

## Goal

An agent in the conversational `AgenticLoop` (AD-1065) can **load** a cognitive skill (its `SKILL.md` body) and **run** its bundled scripts via `run_python` (AD-1066). The bridge between `CognitiveSkillCatalog` (AD-596a) and the code-execution tool.

## Verified facts (grepped against HEAD, do not re-derive)

- `runtime.cognitive_skill_catalog: CognitiveSkillCatalog | None` — the catalog attribute (`runtime.py:835`).
- `CognitiveSkillCatalog` (`cognitive/skill_catalog.py`) API:
  - `get_entry(name) -> CognitiveSkillEntry | None` — `.skill_dir: Path`, `.description`, `.name`.
  - `get_instructions(name) -> str | None` — the `SKILL.md` body below the frontmatter (on-demand load).
  - `list_entries(department=None, min_rank=None) -> list[CognitiveSkillEntry]` — dept/rank-filtered visibility (`min_rank` = the *agent's* rank).
- `SubprocessSandbox` (`execution/isolation.py`) is **Tier-1 confinement-by-convention** — its own module docstring (lines 11–20): *"A determined script can still read host files by absolute path."* ⇒ a skill's scripts run from `skill_dir` **by absolute path** inside `run_python`; **no sandbox change is required**. The sandbox runs `[py, "-I", "-B", script]` (isolated mode) so the generated code must use `subprocess.run([sys.executable, <abs script>], …)` or `sys.path.insert(0, <abs skill_dir>)` — both work at runtime under `-I`.
- `Tool` protocol (`tools/protocol.py`): `tool_id`, `name`, `tool_type`, `description`, `input_schema`, `output_schema`, `async invoke(params, context=None) -> ToolResult`. `ToolResult(output=…, error=…, duration_ms=…)`; `.success == (error is None)`.
- Loop tool-registration site: `cognitive/agentic_dispatch.py` `WorkItemAgenticExecutor.run` — the `exec_ids` block (~`555–566`) registers `CodeExecutionTool` idempotently (`if registry.get("run_python") is None: registry.register(tool, provider=…, tags=…)`), then `tool_ids = list(dict.fromkeys([*granted_ids, *mesh_ids, *mcp_ids, *exec_ids]))` (~`568`). The loop `context` already carries `{agent_id, department, rank, thread_id}` (~`590`).

## Deliverables

### 1. New file `src/probos/tools/use_skill_tool.py`

`UseSkillTool` (duck-typed `Tool`, `tool_id="use_skill"`, `ToolType.UTILITY_AGENT`), constructed `UseSkillTool(runtime=runtime)`:

- `input_schema`: `{name: string (required)}`.
- `description`: explains it loads a named skill's instructions + bundled scripts; tells the model to run the returned scripts via `run_python` using the absolute `skill_dir`; says calling it without a known name returns the available list.
- `invoke(params, context)`:
  - no catalog → `ToolResult(error=…)`.
  - `name` resolved + dept/rank visibility checked via `list_entries(department=ctx["department"], min_rank=ctx["rank"])`.
  - found + visible → `ToolResult(output={found: True, name, description, instructions (body), skill_dir (abs str), files: [{path (rel), abs}]})`. `files` = every file under `skill_dir` except `SKILL.md` and skip-dirs (`__pycache__`, `.git`, …), bounded (≤200).
  - not found / not visible → `ToolResult(output={found: False, available: [names…]}, error=…)` (honest-degrade, AD-592).
  - never raises out of `invoke` (honest-degrade; log-and-degrade).

### 2. Wire into the loop — `cognitive/agentic_dispatch.py`

After the `exec_ids` block, add a `skill_ids` block:

```python
# AD-1068: offer the use_skill tool whenever the cognitive-skill catalog is
# wired — it loads a skill's SKILL.md body + bundled-script manifest into the
# loop so the agent can run the skill's scripts via run_python (AD-1066).
# Read-only (does not itself require execution.enabled); idempotent register.
skill_ids: list[str] = []
if getattr(runtime, "cognitive_skill_catalog", None) is not None and registry is not None:
    try:
        from probos.tools.use_skill_tool import UseSkillTool
        if registry.get("use_skill") is None:
            registry.register(UseSkillTool(runtime=runtime), provider="AD-1068", tags=["use_skill", "skills"])
        skill_ids = ["use_skill"]
    except Exception:
        logger.warning("AD-1068: failed to register/offer use_skill for agent %s; continuing", agent_id, exc_info=True)
        skill_ids = []
```

Add `*skill_ids` to the `tool_ids` dedup: `list(dict.fromkeys([*granted_ids, *mesh_ids, *mcp_ids, *exec_ids, *skill_ids]))`.

### 3. Tests `tests/test_ad1068_use_skill_tool.py`

- unit: catalog-absent error; name-missing error; found returns body + abs `skill_dir` + file manifest; not-found honest-degrade returns `available`; dept/rank visibility excludes an out-of-dept skill.
- loop integration: a fixture skill `config/skills/<tmp>/` (frontmatter + `scripts/make.py` that writes a file) staged in `tmp_path`; a scripted-LLM `WorkItemAgenticExecutor` loop calls `use_skill` then `run_python` (abs path to the script) → the script's output file is captured as a real artifact on the thread. Reuse the AD-1066 `_ScriptedLLM` / `_FakeAttachmentStore` / `_loop_runtime` harness shapes.

## Do NOT change

- `CodeExecutionTool` / `run_python` (AD-1066) — unchanged; `use_skill` is additive.
- `SubprocessSandbox` / `execution/isolation.py` — abs-path reads are the documented Tier-1 behavior; do not add staging/copying in this AD.
- The task-path callers of `WorkItemAgenticExecutor` (AD-839/859) — only ADD the `skill_ids` block; the dedup list order is append-only.
- `config/system.yaml` — never commit it.

## Acceptance

`test_ad1068_*` green; AD-1066 + AD-1065 regression green; no change to the flag-off behavior. Verify Engineering Principles compliance (`.github/copilot-instructions.md`).
