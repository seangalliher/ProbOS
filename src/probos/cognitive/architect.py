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

    # -- tier override --------------------------------------------------------

    def _resolve_tier(self) -> str:
        """Architect uses deep tier for thorough analysis."""
        return "deep"

    # -- lifecycle overrides --------------------------------------------------

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
                    f"- {f['path']} (relevance: {f['relevance']}, summary: {f.get('docstring', 'N/A')})"
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
