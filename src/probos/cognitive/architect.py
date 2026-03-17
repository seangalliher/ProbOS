"""ArchitectAgent — roadmap-driven BuildSpec generation (AD-306).

A CognitiveAgent in the Science team that analyzes ProbOS's roadmap,
codebase, and knowledge store to produce structured ArchitectProposal
objects containing BuildSpec proposals for the Builder Agent.

The Architect does NOT write code.  It writes *specifications* — the same
structured BuildSpec that the Builder Agent already consumes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from probos.cognitive.builder import BuildSpec
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import IntentDescriptor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes (AD-306)
# ---------------------------------------------------------------------------

@dataclass
class ArchitectProposal:
    """A structured proposal from the Architect Agent."""

    title: str
    summary: str
    rationale: str
    build_spec: BuildSpec
    roadmap_ref: str = ""
    priority: str = "medium"
    dependencies: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ArchitectAgent (AD-306)
# ---------------------------------------------------------------------------

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

    # -- tier override --------------------------------------------------------

    def _resolve_tier(self) -> str:
        """Architect uses deep tier for thorough analysis."""
        return "deep"

    # -- lifecycle overrides --------------------------------------------------

    async def perceive(self, intent: Any) -> dict:
        """Gather 7 layers of codebase context for architectural design."""
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
            # Layer 1: Full file tree by architectural layer
            try:
                layer_map = codebase_index.get_layer_map()
                if layer_map:
                    tree_lines = ["## File Tree"]
                    for layer, files in sorted(layer_map.items()):
                        tree_lines.append(f"\n### {layer} ({len(files)} files)")
                        for f in sorted(files):
                            tree_lines.append(f"  {f}")
                    context_parts.append("\n".join(tree_lines))
            except Exception:
                pass

            # Layer 2: Relevant files with source snippets
            try:
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
                            if source else f"\n### {path} (relevance: {f['relevance']}) \u2014 could not read"
                        )
                    context_parts.append("\n".join(relevant_parts))
            except Exception:
                pass

            # Layer 3: Existing slash commands
            try:
                shell_source = codebase_index.read_source(
                    "experience/shell.py", start_line=31, end_line=65
                )
                if shell_source:
                    context_parts.append(f"## Existing Slash Commands (shell.py)\n```\n{shell_source}\n```")
            except Exception:
                pass

            context_parts.append(
                "## Inline API Commands (not in shell.py COMMANDS)\n"
                "- /build <title>: <description> \u2014 handled in api.py, triggers BuilderAgent\n"
                "- /design <feature> \u2014 handled in api.py, triggers ArchitectAgent"
            )

            # Layer 4: Existing API routes
            try:
                api_source = codebase_index.read_source("api.py")
                if api_source:
                    routes: list[str] = []
                    for line in api_source.splitlines():
                        stripped = line.strip()
                        if stripped.startswith("@app.") and "(" in stripped:
                            routes.append(f"  {stripped}")
                        elif stripped.startswith("async def ") and routes:
                            func_name = stripped.split("(")[0].replace("async def ", "")
                            routes[-1] += f"  \u2192  {func_name}()"
                    if routes:
                        context_parts.append("## Existing API Routes\n" + "\n".join(routes))
            except Exception:
                pass

            # Layer 5: Agent map + pool/crew structure
            try:
                agent_map = codebase_index.get_agent_map()
                if agent_map:
                    context_parts.append("## Registered Agents\n" + "\n".join(
                        f"- {a['type']} ({a.get('tier', '?')}) [{a.get('module', '')}]: bases={a.get('bases', [])}"
                        for a in agent_map
                    ))
            except Exception:
                pass

            try:
                runtime = getattr(self, "_runtime", None)
                if runtime and hasattr(runtime, "pool_groups") and hasattr(runtime, "pools"):
                    group_status = runtime.pool_groups.status(runtime.pools)
                    if group_status:
                        pool_lines = ["## Pool Groups (Crew Structure)"]
                        for gname, gdata in group_status.items():
                            display = gdata.get("display_name", gname)
                            pools = list(gdata.get("pools", {}).keys())
                            pool_lines.append(f"- {display}: pools={pools}")
                        context_parts.append("\n".join(pool_lines))
            except Exception:
                pass

            # Layer 6: Documentation context
            try:
                roadmap_path = "docs:docs/development/roadmap.md"
                keywords = feature.lower().split()
                if phase:
                    keywords.append(f"phase {phase}")
                sections = codebase_index.read_doc_sections(
                    roadmap_path, keywords, max_lines=200
                )
                if sections:
                    context_parts.append(f"## Roadmap Context\n{sections}")
            except Exception:
                pass

            try:
                progress_path = "docs:PROGRESS.md"
                keywords = feature.lower().split()
                if phase:
                    keywords.append(f"phase {phase}")
                progress_sections = codebase_index.read_doc_sections(
                    progress_path, keywords, max_lines=100
                )
                if progress_sections:
                    context_parts.append(f"## Progress Context\n{progress_sections}")
            except Exception:
                pass

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

            # Layer 7: Sample build prompt for format calibration
            try:
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
            except Exception:
                pass

        obs["codebase_context"] = "\n\n".join(context_parts)
        return obs

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

    # -- proposal parser ------------------------------------------------------

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
