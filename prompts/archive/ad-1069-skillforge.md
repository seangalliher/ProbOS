# AD-1069 — SkillForge: generate, validate, smoke-test + register cognitive skills

**Issue:** seangalliher/ProbOS#1008 · **Epic:** #1006 · **Supersedes** the epic's hand-authored "document skills (docx first)" line with a generative approach.

**Current highest minted top-level AD: AD-1068** (this session, uncommitted). This is **AD-1069**.

---

## Goal

A utility that GENERATES original cognitive skills (`SKILL.md` + a self-contained bundled script) on demand — the skill-side sibling of `AgentDesigner`/`SkillDesigner`. The output is an AD-596a cognitive skill that the AD-1068 `use_skill` tool loads and the AD-1066 `run_python` tool runs. License-clean by construction (generated from public-library knowledge; never copies a proprietary skill library).

## Verified facts (grepped against HEAD)

- `CognitiveSkillCatalog.import_skill(source_path: Path, origin="external") -> CognitiveSkillEntry` (`skill_catalog.py:647`): validates `SKILL.md` via `parse_skill_file`, **duplicate-guards on name**, `shutil.copytree` into `config/skills/<name>`, sets `origin` + `skill_dir`, registers. Raises `ValueError` on invalid/duplicate/no-skills-dir. ⇒ the forge stages into a temp dir, then `import_skill(staging, origin="generated")`.
- `parse_skill_file(path) -> CognitiveSkillEntry | None` + `_validate_spec(entry) -> list[str]` (structural, AgentSkills.io name rules) + `get_skill_body(path)` — module-level helpers in `skill_catalog.py`.
- `CodeValidator.validate` (`code_validator.py`) requires a BaseAgent/CognitiveAgent **class** (`_check_schema`) ⇒ **wrong for skill scripts**; use `ast.parse` (syntax) + a minimal dangerous-pattern scan instead. The real boundary is the sandbox smoke-test.
- `SubprocessSandbox.run(ExecutionRequest(code=…|argv=…, workdir=…, timeout_seconds=…, …))` (`execution/isolation.py`): when `workdir is None` it creates AND `shutil.rmtree`s an ephemeral dir in `finally` ⇒ to inspect produced files the forge MUST pass its own `workdir`. Sandbox writes `code` to `script.py` in the workdir and runs `[py, -I, -B, script.py]` with `cwd=workdir`.
- LLM gen pattern (`SkillDesigner`): `LLMRequest(prompt=…, tier="deep", max_tokens=…)`, `await llm.complete(req)` → `.content`/`.error`; strip ```python fences.
- Installed doc libs in `.venv`: `docx` (python-docx), `openpyxl`, `pptx` (python-pptx), `pypdf` ✓; `reportlab` ✗ (crew-tools).

## Deliverables

### 1. New file `src/probos/cognitive/skill_forge.py`

`SkillForge`, constructor-injected: `SkillForge(*, llm_client, catalog, sandbox=None, tier="deep")`.

- `ForgeResult` dataclass: `success: bool`, `name`, `skill_dir`, `errors: list[str]`, `smoke_artifacts: list[str]`, `skill_md`.
- `async forge(*, name, description, task, department="*", min_rank="ensign", primary_script="scripts/generate.py") -> ForgeResult`:
  1. **Generate** — one deep-tier LLM call; prompt emits `===FILE: SKILL.md===` + `===FILE: scripts/generate.py===` blocks (the BuilderAgent CREATE convention). Honest-degrade on empty/error.
  2. **Stage** — parse blocks (strip an outer code fence), write to a `tempfile.mkdtemp` dir; **path-traversal guard** (`..`/absolute → reject — the LLM output is untrusted).
  3. **Validate** — `parse_skill_file` (frontmatter), name == requested, `_validate_spec` (structural), and for each `scripts/*.py`: `ast.parse` (syntax) + dangerous-pattern scan (`eval`/`exec`/`__import__`/`os.system`/`socket`/`ctypes`). Any error ⇒ `success=False`, **no registration**.
  4. **Smoke-test** — run the primary script's content via `sandbox.run(ExecutionRequest(code=…, workdir=<own temp>, timeout, max_*))`; PASS = exit 0 AND ≥1 non-`script.py` file produced in the workdir. Fail ⇒ `success=False`, **no registration**.
  5. **Register** — `catalog.import_skill(staging, origin="generated")`; surface a duplicate-name `ValueError` as a clean error.
  - `try/finally` cleans the staging + smoke temp dirs. Never raises out of `forge`.
- The generation prompt mandates a **self-contained** primary script that, run with no args, writes a sample deliverable to cwd by plain filename, with an editable `CONFIG` block on top; only stdlib + installed permissive libs; no network/subprocess/eval/exec. Produce ORIGINAL work (never copy a proprietary skill library).

### 2. Tests `tests/test_ad1069_skill_forge.py`

Scripted-LLM (canned `===FILE:` blocks) + REAL `SubprocessSandbox` + REAL `CognitiveSkillCatalog(skills_dir=tmp)`:
- forge a **docx** skill → `success`, registered with `origin="generated"`, then run the REGISTERED `scripts/generate.py` in the sandbox → a real, re-openable `.docx` (`Document(io.BytesIO(...))`).
- forge an **xlsx** (openpyxl) and a **csv** (stdlib) skill → real artifacts.
- honest-degrade, no registration: bad `SKILL.md` (no `name`); script `SyntaxError`; smoke-test produces no file; forbidden pattern (`eval`); empty LLM output; duplicate name.

## Do NOT change

- The existing `SkillDesigner` (intent-handler-function generator — different abstraction) — leave it.
- `import_skill` / `parse_skill_file` / `_validate_spec` — reuse, don't modify.
- `CodeExecutionTool` / `use_skill_tool` / `agentic_dispatch` — the forge is an independent utility; an agent-facing `forge_skill` tool is a noted follow-on (not this AD).
- `config/system.yaml` — never commit.

## Acceptance

`test_ad1069_*` green; AD-1066/1068 regression green. License-clean (generated originals; no proprietary skill copied). Verify Engineering Principles compliance (`.github/copilot-instructions.md`).
