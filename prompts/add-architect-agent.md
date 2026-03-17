# AD-306: Architect Agent — Roadmap-Driven Build Spec Generation

*"The First Officer surveys the star charts, identifies the next heading, and drafts the orders — the Captain approves, the Engineer executes."*

The Architect Agent is a CognitiveAgent in the Science team that analyzes ProbOS's roadmap, codebase, and knowledge store to produce structured `BuildSpec` proposals for the Builder Agent. It bridges the gap between "what should we build next?" and "here's the exact spec to build it." This is step 3 of the automated builder northstar — the piece that replaces the human architect writing build prompts manually.

The Architect does NOT write code. It writes *specifications* — the same structured `BuildSpec` that the Builder Agent already consumes. The Captain reviews and approves the spec, then it flows to the Builder Agent via the existing API.

**Current AD count:** AD-305. This prompt uses AD-306+.
**Current test count:** 1790 pytest + 21 vitest.

---

## Pre-Build Audit

Read these files before writing any code:

1. `src/probos/cognitive/cognitive_agent.py` — CognitiveAgent base class, lifecycle methods (perceive, decide, act, report), `_resolve_tier()`, `_build_user_message()`, `handle_intent()`
2. `src/probos/cognitive/builder.py` — BuilderAgent pattern, BuildSpec/BuildResult dataclasses (lines 28-56), IntentDescriptor declaration (lines 134-150), instructions string (lines 152-182), perceive override (lines 192-210), `_build_user_message()` (lines 212-238), act override (lines 240-262)
3. `src/probos/cognitive/codebase_index.py` — `query()`, `read_source()`, `read_doc_sections()`, `get_agent_map()`, `get_layer_map()`, `get_api_surface()`
4. `src/probos/cognitive/codebase_skill.py` — `create_codebase_skill()` pattern for attaching CodebaseIndex to agents
5. `src/probos/runtime.py` lines 235-265 — template registration pattern; lines 480-490 — pool creation for builder; lines 524-531 — codebase_skill attachment; lines 540-587 — PoolGroup registration
6. `src/probos/types.py` lines 384-397 — IntentDescriptor dataclass
7. `src/probos/api.py` lines 108-127 — BuildRequest/BuildApproveRequest models; lines 581-616 — build submit/approve endpoints; lines 618-722 — `_run_build()` pipeline
8. `PROGRESS.md` — status line format (line 3), era table, AD numbering pattern
9. `docs/development/roadmap.md` — phase structure, team details, feature descriptions

---

## What To Build

### Step 1: ArchitectProposal dataclass (AD-306)

**File:** `src/probos/cognitive/architect.py` (new file)

Create an `ArchitectProposal` dataclass that captures the Architect Agent's output — a reasoned recommendation with an embedded `BuildSpec`:

```python
from probos.cognitive.builder import BuildSpec

@dataclass
class ArchitectProposal:
    """A structured proposal from the Architect Agent."""
    title: str                              # e.g. "Add Network Egress Policy"
    summary: str                            # 2-3 sentence overview of what and why
    rationale: str                          # Why now? What roadmap item does this address?
    build_spec: BuildSpec                   # The spec for the Builder Agent
    roadmap_ref: str = ""                   # e.g. "Phase 31 — Security Team"
    priority: str = "medium"               # "high", "medium", "low"
    dependencies: list[str] = field(default_factory=list)  # What must exist before this
    risks: list[str] = field(default_factory=list)         # Known risks or concerns
```

Import `BuildSpec` from `probos.cognitive.builder`. Do NOT duplicate the BuildSpec definition.

### Step 2: ArchitectAgent class (AD-306)

**File:** `src/probos/cognitive/architect.py` (same file)

Create the `ArchitectAgent` as a CognitiveAgent:

```python
class ArchitectAgent(CognitiveAgent):
    """Science-team agent that analyzes the roadmap and codebase to propose BuildSpecs."""

    agent_type = "architect"
    tier = "domain"
    _handled_intents = {"design_feature"}
    intent_descriptors = [
        IntentDescriptor(
            name="design_feature",
            params={
                "feature": "Description of the feature or roadmap item to design",
                "phase": "Optional phase number for context (e.g. '31')",
            },
            description=(
                "Analyze the ProbOS roadmap and codebase to design a BuildSpec "
                "for a specific feature. Reads existing code patterns, identifies "
                "target files, reference files, and constraints, then produces "
                "a structured proposal for Captain review."
            ),
            requires_consensus=False,
            requires_reflect=True,
            tier="domain",
        ),
    ]
```

**Key design decisions:**
- `requires_consensus=False` — architectural proposals go directly to Captain, not to agent consensus. The Captain is the approval gate.
- `requires_reflect=True` — architectural reasoning benefits from the reflect cycle (self-check the proposal before returning it).
- Single intent `design_feature` — takes a feature description and optional phase context.

**Instructions string** — the system prompt that tells the LLM how to be an architect. This is critical. It should include:

```python
    instructions = """You are the Architect Agent for ProbOS, a probabilistic agent-native operating system.
Your job is to analyze the codebase and roadmap, then produce detailed BuildSpec proposals
that the Builder Agent can execute.

You have access to:
- The ProbOS codebase structure (files, agents, layers, API surfaces)
- Project documentation (PROGRESS.md, roadmap, DECISIONS.md)
- Knowledge from prior episodes and decisions

When asked to design a feature:

1. UNDERSTAND THE REQUEST — What roadmap item or feature is being requested?
   Identify the relevant phase, team, and architectural layer.

2. SURVEY THE CODEBASE — Find existing patterns that the new feature should follow.
   Identify the files that will need to be created or modified.
   Read the source of the most relevant existing implementations.

3. IDENTIFY DEPENDENCIES — What existing code does this feature build on?
   What must be read as reference to maintain consistency?

4. DESIGN THE SPEC — Produce a structured proposal with:
   - title: Short, descriptive (e.g. "Add Network Egress Policy")
   - description: Detailed specification covering WHAT to build, HOW it fits
     into the architecture, and the exact classes/functions to create
   - target_files: Files to create or modify (full paths from repo root)
   - reference_files: Files the Builder must read for context (full paths)
   - test_files: Test files to create (follow the tests/test_*.py pattern)
   - ad_number: Next available AD number (scan DECISIONS.md for the latest)
   - constraints: Specific "Do NOT" rules to prevent scope creep

5. ASSESS RISKS — What could go wrong? What are the tricky parts?

OUTPUT FORMAT:
Return your proposal as a structured block:

===PROPOSAL===
TITLE: <title>
SUMMARY: <2-3 sentences>
RATIONALE: <why this, why now>
ROADMAP_REF: <phase and team reference>
PRIORITY: <high|medium|low>
AD_NUMBER: <next AD number>

TARGET_FILES:
- <path>
- <path>

REFERENCE_FILES:
- <path>
- <path>

TEST_FILES:
- <path>

CONSTRAINTS:
- <constraint>
- <constraint>

DEPENDENCIES:
- <dependency>

RISKS:
- <risk>

DESCRIPTION:
<detailed multi-paragraph specification of what to build, including
class signatures, method signatures, and architectural decisions.
This becomes the Builder Agent's primary input.>
===END PROPOSAL===

IMPORTANT RULES:
- Be SPECIFIC about file paths — use full paths from repo root (e.g. src/probos/security/egress.py)
- Reference existing patterns — tell the Builder which files to read and which patterns to follow
- Include test expectations — how many test classes, what to cover
- One proposal per response — do not bundle multiple features
- Do NOT write implementation code — write specifications only
- Respect the "Do NOT Build" boundary — if something is deferred, say so in constraints
"""
```

**`_resolve_tier()` override:**

```python
    def _resolve_tier(self) -> str:
        """Architect uses deep tier for thorough analysis."""
        return "deep"
```

**`perceive()` override** — this is where the Architect gathers codebase context. It should use the runtime's `codebase_index` to query relevant files and documentation:

```python
    async def perceive(self, intent: Any) -> dict:
        """Gather codebase structure and documentation context."""
        obs = await super().perceive(intent)
        params = obs.get("params", {})
        feature = params.get("feature", "")
        phase = params.get("phase", "")

        context_parts: list[str] = []

        # Access codebase_index through runtime
        codebase_index = getattr(self, "_runtime", None)
        if codebase_index:
            codebase_index = getattr(codebase_index, "codebase_index", None)

        if codebase_index:
            # Query for relevant files
            query_results = codebase_index.query(feature)
            if query_results.get("matching_files"):
                context_parts.append("## Relevant Files\n" + "\n".join(
                    f"- {f['path']} (score: {f['score']}, summary: {f.get('docstring', 'N/A')})"
                    for f in query_results["matching_files"][:10]
                ))

            # Get agent map for understanding existing agents
            agent_map = codebase_index.get_agent_map()
            if agent_map:
                context_parts.append("## Existing Agents\n" + "\n".join(
                    f"- {a['type']} ({a.get('tier', '?')}): {a.get('bases', [])}"
                    for a in agent_map[:20]
                ))

            # Read roadmap sections relevant to the feature
            roadmap_path = "docs:docs/development/roadmap.md"
            keywords = feature.lower().split()
            if phase:
                keywords.append(f"phase {phase}")
            sections = codebase_index.read_doc_sections(
                roadmap_path, keywords, max_lines=200
            )
            if sections:
                context_parts.append(f"## Roadmap Context\n{sections}")

            # Read PROGRESS.md for current state
            progress_path = "docs:PROGRESS.md"
            progress_sections = codebase_index.read_doc_sections(
                progress_path, keywords, max_lines=100
            )
            if progress_sections:
                context_parts.append(f"## Progress Context\n{progress_sections}")

            # Read DECISIONS.md tail to find latest AD number
            try:
                decisions_content = codebase_index.read_source(
                    "docs:DECISIONS.md", start_line=None, end_line=None
                )
                if decisions_content:
                    # Extract last 30 lines to find the latest AD number
                    lines = decisions_content.strip().split("\n")
                    tail = "\n".join(lines[-30:])
                    context_parts.append(f"## Recent Decisions (tail)\n{tail}")
            except Exception:
                pass

            # Get layer map for architectural context
            layer_map = codebase_index.get_layer_map()
            if layer_map:
                context_parts.append("## Architecture Layers\n" + "\n".join(
                    f"- {layer}: {len(files)} files"
                    for layer, files in layer_map.items()
                ))

        obs["codebase_context"] = "\n\n".join(context_parts)
        return obs
```

**How to access the runtime:** The CognitiveAgent receives a `runtime` kwarg in its constructor (passed by `create_pool`). Store it as `self._runtime`. Check how other agents access runtime — look at `cognitive_agent.py` constructor for the pattern. The runtime ref may already be stored. If it is, use the existing attribute. If not, accept `runtime` kwarg in `__init__` and store it:

```python
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        runtime = kwargs.pop("runtime", None)
        super().__init__(*args, **kwargs)
        self._runtime = runtime
```

**Important:** Check the CognitiveAgent constructor signature first. It may already store `runtime`. If so, do NOT duplicate it. Just use `self.runtime` or `self._runtime` (whatever the base class calls it). The builder agent also receives `runtime=self` in `create_pool()` — follow the same pattern.

**`_build_user_message()` override:**

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
            "## Codebase Context",
            codebase_context if codebase_context else "(no codebase context available)",
            "",
            "Based on the above context, produce an ===PROPOSAL=== block with a "
            "complete BuildSpec for this feature.",
        ]
        return "\n".join(p for p in parts if p is not None)
```

**`act()` override** — parse the `===PROPOSAL===` block from the LLM output:

```python
    async def act(self, decision: dict) -> dict:
        """Parse LLM output into an ArchitectProposal."""
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}

        llm_output = decision.get("llm_output", "")
        proposal = self._parse_proposal(llm_output)

        if proposal is None:
            return {
                "success": False,
                "error": "No ===PROPOSAL=== block found in LLM output",
                "llm_output": llm_output,
            }

        return {
            "success": True,
            "result": {
                "proposal": {
                    "title": proposal.title,
                    "summary": proposal.summary,
                    "rationale": proposal.rationale,
                    "roadmap_ref": proposal.roadmap_ref,
                    "priority": proposal.priority,
                    "dependencies": proposal.dependencies,
                    "risks": proposal.risks,
                    "build_spec": {
                        "title": proposal.build_spec.title,
                        "description": proposal.build_spec.description,
                        "target_files": proposal.build_spec.target_files,
                        "reference_files": proposal.build_spec.reference_files,
                        "test_files": proposal.build_spec.test_files,
                        "ad_number": proposal.build_spec.ad_number,
                        "constraints": proposal.build_spec.constraints,
                    },
                },
                "llm_output": llm_output,
            },
        }
```

**`_parse_proposal()` static method** — extracts the structured proposal from the LLM's `===PROPOSAL===...===END PROPOSAL===` block:

```python
    @staticmethod
    def _parse_proposal(text: str) -> ArchitectProposal | None:
        """Parse an ===PROPOSAL=== block into an ArchitectProposal."""
        match = re.search(
            r"===PROPOSAL===(.*?)===END PROPOSAL===", text, re.DOTALL
        )
        if not match:
            return None

        block = match.group(1).strip()

        def _extract(label: str) -> str:
            """Extract a single-line field value."""
            m = re.search(rf"^{label}:\s*(.+)$", block, re.MULTILINE)
            return m.group(1).strip() if m else ""

        def _extract_list(label: str) -> list[str]:
            """Extract a multi-line list field (lines starting with '- ')."""
            pattern = rf"^{label}:\s*\n((?:- .+\n?)+)"
            m = re.search(pattern, block, re.MULTILINE)
            if not m:
                return []
            return [
                line.lstrip("- ").strip()
                for line in m.group(1).strip().split("\n")
                if line.strip().startswith("- ")
            ]

        def _extract_block(label: str) -> str:
            """Extract a multi-line block field (everything after LABEL: to next section or end)."""
            pattern = rf"^{label}:\s*\n([\s\S]*?)(?=\n[A-Z_]+:|\Z)"
            m = re.search(pattern, block, re.MULTILINE)
            return m.group(1).strip() if m else ""

        title = _extract("TITLE")
        ad_str = _extract("AD_NUMBER")
        ad_number = 0
        if ad_str:
            # Handle "AD-306" or "306" formats
            digits = re.search(r"\d+", ad_str)
            if digits:
                ad_number = int(digits.group())

        spec = BuildSpec(
            title=title,
            description=_extract_block("DESCRIPTION"),
            target_files=_extract_list("TARGET_FILES"),
            reference_files=_extract_list("REFERENCE_FILES"),
            test_files=_extract_list("TEST_FILES"),
            ad_number=ad_number,
            constraints=_extract_list("CONSTRAINTS"),
        )

        return ArchitectProposal(
            title=title,
            summary=_extract("SUMMARY"),
            rationale=_extract("RATIONALE"),
            build_spec=spec,
            roadmap_ref=_extract("ROADMAP_REF"),
            priority=_extract("PRIORITY") or "medium",
            dependencies=_extract_list("DEPENDENCIES"),
            risks=_extract_list("RISKS"),
        )
```

### Step 3: Runtime registration (AD-307)

**File:** `src/probos/runtime.py` (existing file)

**3a. Import and register template:**

Near the other cognitive imports (around line 43-46), add:

```python
from probos.cognitive.architect import ArchitectAgent
```

Near the other `register_template` calls (after line 264), add:

```python
self.spawner.register_template("architect", ArchitectAgent)
```

**3b. Create pool:**

Near the builder pool creation (around lines 480-486), under the same `if self.config.bundled_agents.enabled:` guard, add:

```python
        # Science team — Architect Agent (AD-307)
        await self.create_pool(
            "architect", "architect", target_size=1,
            llm_client=self.llm_client, runtime=self,
        )
```

**3c. Add to pool group:**

Update the engineering pool group (lines 582-587) — actually, the Architect Agent belongs to the **Science** team, not Engineering. Create a new "science" pool group right after the engineering one:

```python
        # Science pool group (AD-307)
        self.pool_groups.register(PoolGroup(
            name="science",
            display_name="Science",
            pool_names={"architect"},
            exclude_from_scaler=True,
        ))
```

**3d. Attach codebase_skill:**

In the codebase_skill attachment section (around lines 524-531), add `"architect"` to the list of pools that get the codebase skill:

```python
            for pool_name in ["medical_pathologist", "architect"]:
```

**3e. Add color to HXI:**

**File:** `ui/src/store/useStore.ts`

Add a color for the science pool group in `GROUP_TINT_HEXES`:

```typescript
science: '#50a0b0',  // teal — for the Science team
```

### Step 4: Tests (AD-306)

**File:** `tests/test_architect_agent.py` (new file)

Write tests covering at least 10 categories:

1. **ArchitectProposal defaults** — verify default field values
2. **ArchitectProposal population** — verify all fields can be set
3. **ArchitectAgent class hierarchy** — inherits from CognitiveAgent, agent_type is "architect"
4. **ArchitectAgent attributes** — `_handled_intents`, `intent_descriptors`, `tier`
5. **ArchitectAgent tier** — `_resolve_tier()` returns "deep"
6. **Proposal parsing — complete** — parse a full `===PROPOSAL===` block with all fields
7. **Proposal parsing — minimal** — parse a block with only required fields, verify defaults
8. **Proposal parsing — no block** — returns None when no `===PROPOSAL===` found
9. **Proposal parsing — AD number formats** — handle "AD-306", "306", "AD-306/307"
10. **User message formatting** — verify `_build_user_message()` includes feature, phase, and codebase context
11. **Perceive with runtime** — mock runtime with codebase_index, verify context is gathered
12. **Perceive without runtime** — verify graceful handling when no codebase_index
13. **Act — success** — mock decision with valid LLM output, verify proposal is parsed
14. **Act — error** — mock decision with action="error", verify error result
15. **Act — no proposal block** — mock decision with LLM output lacking ===PROPOSAL===, verify error

Follow the test patterns from `tests/test_builder_agent.py`. Use `unittest.mock.AsyncMock` for async mocks. Use `pytest` style (no `unittest.TestCase`). Group tests into classes by category.

**Run tests after this step:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_architect_agent.py -x -q`

---

## AD Summary

| AD | Decision |
|----|----------|
| AD-306 | ArchitectAgent — CognitiveAgent (Science team, deep tier) that reads roadmap, codebase, and knowledge store to produce structured ArchitectProposal containing a BuildSpec for the Builder Agent. Parses ===PROPOSAL=== blocks from LLM output. |
| AD-307 | Runtime integration — register architect template, create pool (target_size=1), add science PoolGroup, attach codebase_skill, add HXI color |

---

## Do NOT Build

- **API endpoints for architect** — future step (AD-308+). For now the Architect Agent is callable only via intent bus broadcast. The API + HXI surface for architect proposals comes next.
- **Automated Architect → Builder pipeline** — future step. For now, the Captain manually reviews the ArchitectProposal and then submits the embedded BuildSpec to the Builder API. The automated handoff comes after both pieces are proven.
- **Research Agent** — the Architect Agent does not search external sources (arxiv, GitHub trending). That's the Research Agent's job, which is a separate future agent.
- **MODIFY block support in Builder** — the Builder currently logs and skips MODIFY blocks. Do not try to fix this in the Architect Agent. The Architect should still list files in `target_files` even if they're modifications — the Builder will handle them as full file creates for now.

---

## Constraints

- Do NOT add new dependencies to `pyproject.toml` — use only existing imports
- Do NOT modify `src/probos/cognitive/builder.py` — import from it, don't change it
- Do NOT modify the existing PoolGroup registrations — add a new one for science
- Do NOT create API endpoints — those come in a future prompt
- Follow existing code style: `from __future__ import annotations`, type hints, dataclass fields with `field(default_factory=list)`, logger via `logging.getLogger(__name__)`
- Run tests: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
- Run vitest too: `cd d:/ProbOS/ui && npx vitest run`

---

## Update PROGRESS.md When Done

Add to the current era progress file (`progress-era-4-evolution.md` or whichever is current):

```
## Phase 32c: Architect Agent (AD-306--307)

| AD | Decision |
|----|----------|
| AD-306 | ArchitectAgent — Science-team CognitiveAgent that analyzes roadmap and codebase to produce structured BuildSpec proposals via ===PROPOSAL=== parsing |
| AD-307 | Runtime integration — architect template, pool, science PoolGroup, codebase_skill attachment, HXI teal color |

**Status:** Complete — N new tests (NNNN Python total)
```

Update the status line test count in `PROGRESS.md` line 3.
