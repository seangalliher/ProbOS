# AD-310: Architect Agent Quality — Perceive Depth + Instruction Hardening

*"An officer who makes decisions without reading the ship's logs is no officer at all."*

The Architect Agent (AD-306) produces proposals, but its first live test revealed two critical failures: it hallucinated file paths that don't exist and proposed a feature (`/agents`) that's already built. Root cause: the `perceive()` method gathers thin context — file paths without source code, no awareness of existing slash commands or API routes, no file tree for path validation.

This prompt upgrades `perceive()` to gather the same quality of context that a human architect uses when drafting build prompts. Same LLM model (deep tier Opus) — the only difference is input quality. Fix the input, fix the output.

**Current AD count:** AD-309. This prompt uses AD-310.
**Current test count:** 1826 pytest + 21 vitest.

---

## Pre-Build Audit

Read these files before writing any code:

1. `src/probos/cognitive/architect.py` — the ENTIRE file. You are modifying `perceive()` (lines 160-232), `_build_user_message()` (lines 234-251), and the `instructions` string (lines 72-150). Do NOT change `act()`, `_parse_proposal()`, or `ArchitectProposal`.
2. `src/probos/cognitive/codebase_index.py` — understand ALL available query methods:
   - `query(concept)` → `{"matching_files": [{"path", "relevance", "docstring"}]}`
   - `read_source(file_path, start_line, end_line)` → source code string
   - `read_doc_sections(doc_path, keywords, max_lines)` → matching sections
   - `get_agent_map()` → `[{"class", "type", "tier", "module", "bases", "capabilities", "intents"}]`
   - `get_layer_map()` → `{"layer_name": ["file/path.py", ...]}` (actual relative paths)
   - `get_api_surface(class_name)` → `[{"name", "signature"}]`
   - `get_config_schema()` → config field info
3. `src/probos/experience/shell.py` lines 31-65 — the `COMMANDS` dict listing all 27+ slash commands
4. `src/probos/api.py` lines 185-209 — how `/build` and `/design` slash commands are handled inline (not in shell.py)
5. `src/probos/runtime.py` lines 540-587 — pool group definitions (crew structure)
6. `prompts/add-architect-api-hxi.md` — the most recent build prompt, to understand the output format quality expected. Read at least the first 80 lines for structure.
7. `tests/test_architect_agent.py` — existing tests you must not break

---

## What To Build

### Step 1: Upgrade `perceive()` — Deep Context Gathering (AD-310)

**File:** `src/probos/cognitive/architect.py` (existing file)

Replace the current `perceive()` method with a version that gathers seven layers of context. The overall structure stays the same (check for `codebase_index`, build `context_parts`, return `obs`) but the content gathered is dramatically richer.

**Layer 1: File tree with actual paths** (CRITICAL — prevents path hallucination)

Instead of just layer names with file counts, inject the full file tree organized by layer. The Architect needs to see actual valid paths to propose valid targets:

```python
            # Layer 1: Full file tree by architectural layer
            layer_map = codebase_index.get_layer_map()
            if layer_map:
                tree_lines = ["## File Tree"]
                for layer, files in sorted(layer_map.items()):
                    tree_lines.append(f"\n### {layer} ({len(files)} files)")
                    for f in sorted(files):
                        tree_lines.append(f"  {f}")
                context_parts.append("\n".join(tree_lines))
```

**Layer 2: Relevant files WITH source code** (CRITICAL — enables pattern matching)

After the keyword query, read the actual source of the top 5 matching files. Truncate each to 80 lines to stay within token budget:

```python
            # Layer 2: Relevant files with source snippets
            query_results = codebase_index.query(feature)
            if query_results.get("matching_files"):
                relevant_parts = ["## Relevant Files (with source)"]
                for f in query_results["matching_files"][:5]:
                    path = f["path"]
                    source = codebase_index.read_source(path, start_line=1, end_line=80)
                    relevant_parts.append(
                        f"\n### {path} (relevance: {f['relevance']})\n"
                        f"{'_Summary: ' + f['docstring'] if f.get('docstring') else ''}\n"
                        f"```python\n{source}\n```"
                        if source else f"\n### {path} (relevance: {f['relevance']}) — could not read"
                    )
                context_parts.append("\n".join(relevant_parts))
```

**Layer 3: Existing slash commands** (prevents duplicate features)

Read the COMMANDS dict from shell.py and the inline commands from api.py:

```python
            # Layer 3: Existing slash commands
            shell_source = codebase_index.read_source(
                "experience/shell.py", start_line=31, end_line=65
            )
            if shell_source:
                context_parts.append(f"## Existing Slash Commands (shell.py)\n```\n{shell_source}\n```")

            # Also note the inline API commands not in shell.py
            context_parts.append(
                "## Inline API Commands (not in shell.py COMMANDS)\n"
                "- /build <title>: <description> — handled in api.py, triggers BuilderAgent\n"
                "- /design <feature> — handled in api.py, triggers ArchitectAgent"
            )
```

**Layer 4: API route surface** (prevents route duplication)

Extract existing API endpoint declarations. Read the api.py file looking for `@app.get` and `@app.post` decorators:

```python
            # Layer 4: Existing API routes
            api_source = codebase_index.read_source("api.py")
            if api_source:
                routes = []
                for line in api_source.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("@app.") and "(" in stripped:
                        routes.append(f"  {stripped}")
                    elif stripped.startswith("async def ") and routes:
                        # Attach the function name to the last route
                        func_name = stripped.split("(")[0].replace("async def ", "")
                        routes[-1] += f"  →  {func_name}()"
                if routes:
                    context_parts.append("## Existing API Routes\n" + "\n".join(routes))
```

**Layer 5: Agent map + pool/crew structure** (shows current crew composition)

Keep the existing agent map but also add pool group structure from the runtime:

```python
            # Layer 5: Agent map
            agent_map = codebase_index.get_agent_map()
            if agent_map:
                context_parts.append("## Registered Agents\n" + "\n".join(
                    f"- {a['type']} ({a.get('tier', '?')}) [{a.get('module', '')}]: bases={a.get('bases', [])}"
                    for a in agent_map
                ))

            # Pool group structure from runtime
            runtime = getattr(self, "_runtime", None)
            if runtime and hasattr(runtime, "pool_groups") and hasattr(runtime, "pools"):
                group_status = runtime.pool_groups.status(runtime.pools)
                if group_status:
                    pool_lines = ["## Pool Groups (Crew Structure)"]
                    for g in group_status:
                        pool_lines.append(
                            f"- {g.get('display_name', g.get('name', '?'))}: "
                            f"pools={g.get('pools', [])}"
                        )
                    context_parts.append("\n".join(pool_lines))
```

**Layer 6: Documentation context** (keep existing, but improve)

Keep the existing roadmap and PROGRESS.md reading, but increase DECISIONS.md tail from 30 lines to 80 lines for better AD number context:

```python
            # Layer 6: Roadmap sections
            roadmap_path = "docs:docs/development/roadmap.md"
            keywords = feature.lower().split()
            if phase:
                keywords.append(f"phase {phase}")
            sections = codebase_index.read_doc_sections(
                roadmap_path, keywords, max_lines=200
            )
            if sections:
                context_parts.append(f"## Roadmap Context\n{sections}")

            # PROGRESS.md
            progress_path = "docs:PROGRESS.md"
            progress_sections = codebase_index.read_doc_sections(
                progress_path, keywords, max_lines=100
            )
            if progress_sections:
                context_parts.append(f"## Progress Context\n{progress_sections}")

            # DECISIONS.md tail (80 lines for better AD number coverage)
            try:
                decisions_content = codebase_index.read_source(
                    "docs:DECISIONS.md", start_line=None, end_line=None
                )
                if decisions_content:
                    lines = decisions_content.strip().split("\n")
                    tail = "\n".join(lines[-80:])
                    context_parts.append(f"## Recent Decisions (last 80 lines)\n{tail}")
            except Exception:
                pass
```

**Layer 7: Sample build prompt** (calibrates output quality)

Read the most recent build prompt so the LLM knows the expected format and level of detail. Only the first 60 lines to show structure:

```python
            # Layer 7: Sample build prompt for format calibration
            sample_prompt = codebase_index.read_source(
                "docs:prompts/add-architect-api-hxi.md", start_line=1, end_line=60
            )
            if sample_prompt:
                context_parts.append(
                    "## Sample Build Prompt (for format reference)\n"
                    "The BuildSpec description you generate should aim for this level of "
                    "detail and specificity:\n"
                    f"```markdown\n{sample_prompt}\n```"
                )
```

### Step 2: Upgrade `instructions` string (AD-310)

**File:** `src/probos/cognitive/architect.py` (same file)

Replace the current `instructions` string (lines 72-150) with a hardened version. Keep the same `===PROPOSAL===` output format. The key additions are **verification rules** that prevent the two failure modes we observed:

```python
    instructions = """You are the Architect Agent for ProbOS, a probabilistic agent-native OS.
Your job is to analyze the codebase and roadmap, then produce detailed BuildSpec proposals
that the Builder Agent can execute.

You receive rich codebase context including:
- The full file tree (every file path in the project)
- Source code of relevant files (first 80 lines each)
- All existing slash commands
- All existing API routes
- The current crew structure (pool groups and pools)
- Roadmap and progress documentation
- Recent architecture decisions with AD numbers
- A sample build prompt showing the expected output quality

CRITICAL VERIFICATION RULES:
1. ONLY propose file paths that appear in the File Tree section or follow an existing
   directory pattern you can see. NEVER invent paths like "src/probos/web/" or
   "src/probos/channels/" unless you see them in the tree.
2. Before proposing a new slash command, CHECK the "Existing Slash Commands" section.
   If the command already exists, do NOT propose it. Instead, suggest enhancements.
3. Before proposing a new API route, CHECK the "Existing API Routes" section.
   If the route already exists, do NOT propose it.
4. Before proposing a new agent type, CHECK the "Registered Agents" section.
   If an agent of that type already exists, do NOT propose a duplicate.
5. READ the source code of relevant files in your context. Your proposal MUST reference
   specific patterns you observed — class names, method signatures, import styles.

DESIGN PROCESS:
1. UNDERSTAND — What feature is requested? Which roadmap phase and crew team?
2. VERIFY — Does this feature already exist? Check commands, routes, agents.
3. SURVEY — Read the source of related files. Identify patterns to follow.
4. LOCATE — Find the exact directory where new files should go (from the File Tree).
5. DESIGN — Produce a spec with concrete class signatures that match existing patterns.
6. CONSTRAIN — Add "Do NOT" rules to prevent scope creep.
7. RISKS — What could go wrong? What are the tricky integration points?

QUALITY EXPECTATIONS:
- The description field should be detailed enough for a Builder Agent to implement
  without additional context. Include class signatures, method signatures, and
  import patterns copied from the reference files.
- Reference files should be real paths you can see in the File Tree.
- Test file paths should follow the existing tests/ directory pattern.
- Constraints should reference specific files NOT to modify.
- Look at the Sample Build Prompt in your context — aim for that level of specificity.

OUTPUT FORMAT:
Return your proposal as a structured block:

===PROPOSAL===
TITLE: <title>
SUMMARY: <2-3 sentences>
RATIONALE: <why this, why now>
ROADMAP_REF: <phase and team reference>
PRIORITY: <high|medium|low>
AD_NUMBER: <next AD number — check Recent Decisions for the latest>

TARGET_FILES:
- <path from file tree or following existing directory pattern>

REFERENCE_FILES:
- <path that EXISTS in the file tree — files the Builder must read>

TEST_FILES:
- <tests/test_*.py path>

CONSTRAINTS:
- <specific "Do NOT" rules>

DEPENDENCIES:
- <what must exist before this can be built>

RISKS:
- <what could go wrong>

DESCRIPTION:
<Detailed multi-paragraph specification. Include:
- Exact class/function signatures with type hints
- Import patterns matching existing code
- Integration points (which existing code calls this, or vice versa)
- Test categories with counts
- What the "Do NOT Build" boundary is
This becomes the Builder Agent's primary input.>
===END PROPOSAL===

IMPORTANT RULES:
- One proposal per response — do not bundle multiple features
- Do NOT write implementation code — write specifications only
- Every file path you mention must be verifiable against your context
- If you cannot find enough context to design confidently, say so in RISKS
"""
```

### Step 3: Update `_build_user_message()` (AD-310)

**File:** `src/probos/cognitive/architect.py` (same file)

Minor update — make the message clearer about what context is available and what's expected:

```python
    def _build_user_message(self, observation: dict) -> str:
        """Format the feature request and codebase context into an LLM prompt."""
        params = observation.get("params", {})
        feature = params.get("feature", "Unknown feature")
        phase = params.get("phase", "")
        codebase_context = observation.get("codebase_context", "")

        parts = [
            f"# Feature Design Request: {feature}",
            f"Phase: {phase}" if phase else "",
            "",
            codebase_context if codebase_context else "(no codebase context available)",
            "",
            "Based on the above context, produce an ===PROPOSAL=== block with a "
            "complete BuildSpec for this feature. Remember to verify all file paths "
            "against the File Tree and check for existing features before proposing.",
        ]
        return "\n".join(p for p in parts if p is not None)
```

### Step 4: Tests (AD-310)

**File:** `tests/test_architect_agent.py` (existing file — ADD tests, do not remove existing ones)

Add new test classes covering the upgraded perceive:

1. **TestPerceiveFileTree** — mock codebase_index.get_layer_map() returning `{"cognitive": ["cognitive/builder.py", "cognitive/architect.py"]}`, verify `"## File Tree"` and actual paths appear in `obs["codebase_context"]`
2. **TestPerceiveSourceSnippets** — mock query() returning matching files, mock read_source() returning code, verify source code appears in context with ` ```python ` fencing
3. **TestPerceiveSlashCommands** — mock read_source("experience/shell.py", ...) returning COMMANDS dict, verify it appears in context
4. **TestPerceiveApiRoutes** — mock read_source("api.py") returning lines with `@app.post("/api/build/submit")`, verify routes are extracted
5. **TestPerceivePoolGroups** — mock runtime with pool_groups.status() returning group data, verify crew structure appears
6. **TestPerceiveDecisionsTail** — mock read_source for DECISIONS.md, verify last 80 lines (not 30) appear
7. **TestPerceiveSamplePrompt** — mock read_source for sample prompt, verify it appears with "format reference" framing
8. **TestPerceiveGracefulDegradation** — mock codebase_index methods raising exceptions, verify perceive still returns obs without crashing

Follow the existing test patterns in the file. Use `unittest.mock.AsyncMock` and `MagicMock`. Group into classes.

**Run tests after this step:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_architect_agent.py -x -q`
**Run full suite:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

---

## AD Summary

| AD | Decision |
|----|----------|
| AD-310 | ArchitectAgent quality upgrade — perceive() now gathers 7 context layers (file tree, source snippets, slash commands, API routes, pool groups, documentation, sample build prompt). Instructions hardened with 5 verification rules preventing path hallucination and duplicate feature proposals. |

---

## Do NOT Build

- **New CodebaseIndex methods** — use only existing query(), read_source(), read_doc_sections(), get_agent_map(), get_layer_map(), get_api_surface(). Do NOT add new methods to CodebaseIndex.
- **Changes to act() or _parse_proposal()** — the output format is fine. Only the input quality (perceive + instructions) needs improvement.
- **ArchitectProposal dataclass changes** — the data model is correct. The proposal fields are sufficient.
- **Changes to api.py or the HXI** — this is perceive-only. The API and frontend are done.
- **Token budget management** — for now, trust the deep tier's 200K context window. If context gets too large in practice, we'll add truncation later.

---

## Constraints

- Do NOT add new dependencies to `pyproject.toml`
- Do NOT modify `act()`, `_parse_proposal()`, or `ArchitectProposal`
- Do NOT modify any file except `src/probos/cognitive/architect.py` and `tests/test_architect_agent.py`
- Do NOT add new methods to `CodebaseIndex` — use existing APIs only
- Wrap each context layer in try/except so a failure in one layer doesn't crash the entire perceive
- Follow existing code style: `from __future__ import annotations`, type hints, logger
- Run tests: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
- Run vitest: `cd d:/ProbOS/ui && npx vitest run`

---

## Update PROGRESS.md When Done

Add to the current era progress file:

```
## Phase 32e: Architect Agent Quality (AD-310)

| AD | Decision |
|----|----------|
| AD-310 | ArchitectAgent perceive() upgraded with 7 context layers (file tree, source snippets, slash commands, API routes, pool groups, docs, sample prompt). Instructions hardened with verification rules preventing path hallucination and duplicate proposals. |

**Status:** Complete — N new tests (NNNN Python total)
```

Update the status line test count in `PROGRESS.md` line 3.
